/**
 * housing_matcher.cpp — FairSplit Housing Compatibility Matcher Implementation
 *
 * Architecture reuse note (see housing_matcher.hpp for full comment):
 *   This file implements the same "priority queue + comparator" pattern used in
 *   order_book.cpp (std::map<int, std::queue<Order>> bids/asks).  Here the
 *   priority is a double "score" instead of an integer price, but the conceptual
 *   model is identical: we enumerate feasible groups, compute a score per group,
 *   then return the top-K by score — just as the LOB returns the top-K price
 *   levels when building a book snapshot.
 */

#include "housing_matcher.hpp"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <iostream>

namespace fairsplit {

// ── Minimal JSON parser (no external deps) ────────────────────────────────────
// We implement only what we need: parse an array of flat objects with string
// and integer fields.

static std::string trim(const std::string& s) {
    size_t a = s.find_first_not_of(" \t\r\n");
    size_t b = s.find_last_not_of(" \t\r\n");
    if (a == std::string::npos) return "";
    return s.substr(a, b - a + 1);
}

static std::string unquote(const std::string& s) {
    if (s.size() >= 2 && s.front() == '"' && s.back() == '"')
        return s.substr(1, s.size() - 2);
    return s;
}

// Extract all top-level key:value pairs from a single JSON object string
// (does not handle nested objects or arrays inside values)
static std::vector<std::pair<std::string,std::string>> parse_flat_object(const std::string& obj) {
    std::vector<std::pair<std::string,std::string>> kv;
    // strip surrounding braces
    size_t start = obj.find('{');
    size_t end   = obj.rfind('}');
    if (start == std::string::npos || end == std::string::npos) return kv;
    std::string inner = obj.substr(start+1, end-start-1);

    size_t pos = 0;
    while (pos < inner.size()) {
        // find key (quoted)
        size_t kq1 = inner.find('"', pos);
        if (kq1 == std::string::npos) break;
        size_t kq2 = inner.find('"', kq1+1);
        if (kq2 == std::string::npos) break;
        std::string key = inner.substr(kq1+1, kq2-kq1-1);

        // find colon
        size_t colon = inner.find(':', kq2+1);
        if (colon == std::string::npos) break;

        // find value (either quoted string or number, ends at comma or end)
        size_t vstart = colon + 1;
        while (vstart < inner.size() && (inner[vstart]==' '||inner[vstart]=='\t')) vstart++;
        std::string val;
        if (vstart < inner.size() && inner[vstart] == '"') {
            // string value
            size_t vq2 = inner.find('"', vstart+1);
            if (vq2 == std::string::npos) break;
            val = inner.substr(vstart, vq2-vstart+1);
            pos = vq2 + 1;
        } else {
            // number or other
            size_t vend = inner.find_first_of(",}", vstart);
            if (vend == std::string::npos) vend = inner.size();
            val = trim(inner.substr(vstart, vend-vstart));
            pos = vend;
        }
        kv.push_back({key, val});
        // advance past comma
        size_t comma = inner.find(',', pos);
        if (comma == std::string::npos) break;
        pos = comma + 1;
    }
    return kv;
}

// Split a JSON array string into individual object strings
static std::vector<std::string> split_json_array(const std::string& arr) {
    std::vector<std::string> objects;
    size_t pos = 0;
    size_t n = arr.size();
    // find first '['
    while (pos < n && arr[pos] != '[') pos++;
    if (pos >= n) return objects;
    pos++;

    while (pos < n) {
        while (pos < n && arr[pos] != '{' && arr[pos] != ']') pos++;
        if (pos >= n || arr[pos] == ']') break;
        // read until matching '}'
        int depth = 0;
        size_t start = pos;
        while (pos < n) {
            if (arr[pos] == '{') depth++;
            else if (arr[pos] == '}') { depth--; if (depth == 0) { pos++; break; } }
            pos++;
        }
        objects.push_back(arr.substr(start, pos - start));
    }
    return objects;
}

std::vector<Candidate> parse_candidates_json(const std::string& json) {
    std::vector<Candidate> candidates;
    auto objects = split_json_array(json);
    for (const auto& obj : objects) {
        auto kv = parse_flat_object(obj);
        Candidate c;
        c.preferred_roommate_count = 2;
        c.smoking_preference = "no_preference";
        for (auto& [k, v] : kv) {
            if (k == "id")                       c.id = unquote(v);
            else if (k == "display_name")        c.display_name = unquote(v);
            else if (k == "max_budget")          c.max_budget = std::stoi(v);
            else if (k == "move_in_date")        c.move_in_date = unquote(v);
            else if (k == "smoking_preference")  c.smoking_preference = unquote(v);
            else if (k == "preferred_roommate_count") c.preferred_roommate_count = std::stoi(v);
        }
        if (!c.id.empty()) candidates.push_back(c);
    }
    return candidates;
}

std::string serialize_groups_json(const std::vector<RoommateGroup>& groups) {
    std::ostringstream oss;
    oss << "[";
    for (size_t gi = 0; gi < groups.size(); gi++) {
        const auto& g = groups[gi];
        if (gi > 0) oss << ",";
        oss << "{\"score\":" << g.score
            << ",\"explanation\":\"" << g.explanation << "\""
            << ",\"members\":[";
        for (size_t mi = 0; mi < g.members.size(); mi++) {
            const auto& m = g.members[mi];
            if (mi > 0) oss << ",";
            oss << "{\"id\":\"" << m.id << "\""
                << ",\"display_name\":\"" << m.display_name << "\""
                << ",\"max_budget\":" << m.max_budget
                << ",\"move_in_date\":\"" << m.move_in_date << "\""
                << ",\"smoking_preference\":\"" << m.smoking_preference << "\""
                << ",\"preferred_roommate_count\":" << m.preferred_roommate_count
                << "}";
        }
        oss << "]}";
    }
    oss << "]";
    return oss.str();
}

// ── Date utilities ─────────────────────────────────────────────────────────────

int HousingMatcher::parse_date_to_days(const std::string& date) {
    // "YYYY-MM-DD" -> approximate days since year 0
    if (date.size() < 10) return 0;
    try {
        int y = std::stoi(date.substr(0, 4));
        int m = std::stoi(date.substr(5, 2));
        int d = std::stoi(date.substr(8, 2));
        // approximate: 365.25 days/year, 30.44 days/month
        return (int)(y * 365.25 + m * 30.44 + d);
    } catch (...) {
        return 0;
    }
}

// ── Scoring ────────────────────────────────────────────────────────────────────
//
// Score mirrors OrderBook price-priority:
//   - budget_slack  ↔  price headroom above the market (more = better bid)
//   - date_overlap  ↔  time priority within a price level (tighter = earlier)
//   - compat_bonus  ↔  order flags bonus (e.g. IOC premium)

double HousingMatcher::score_group(const std::vector<Candidate>& group,
                                    int per_person_rent_cents) {
    double total = 0.0;
    std::vector<int> dates;
    std::string first_smoke = group.empty() ? "no_preference" : group[0].smoking_preference;
    bool all_same_smoke = true;

    for (const auto& c : group) {
        // budget_slack: what fraction of the per-person rent is the headroom
        double slack = static_cast<double>(c.max_budget - per_person_rent_cents)
                       / per_person_rent_cents * 100.0;
        total += slack;

        dates.push_back(parse_date_to_days(c.move_in_date));

        if (c.smoking_preference != first_smoke &&
            c.smoking_preference != "no_preference" &&
            first_smoke != "no_preference") {
            all_same_smoke = false;
        }
    }

    // date_overlap_score: max(0, 30 - spread_days)
    if (!dates.empty()) {
        int min_d = *std::min_element(dates.begin(), dates.end());
        int max_d = *std::max_element(dates.begin(), dates.end());
        int spread = max_d - min_d;
        double overlap = std::max(0.0, 30.0 - static_cast<double>(spread));
        total += overlap * static_cast<double>(group.size()); // scale by group size
    }

    // compatibility bonus (per member)
    if (all_same_smoke) {
        total += 10.0 * static_cast<double>(group.size());
    }

    return total;
}

// ── Hard-constraint filtering ─────────────────────────────────────────────────

bool HousingMatcher::is_compatible(const std::vector<Candidate>& group,
                                    int per_person_rent_cents) {
    if (group.empty()) return false;

    // 1. All candidates must afford per-person rent
    for (const auto& c : group) {
        if (c.max_budget < per_person_rent_cents) return false;
    }

    // 2. Move-in dates within 30 days
    std::vector<int> dates;
    for (const auto& c : group) {
        dates.push_back(parse_date_to_days(c.move_in_date));
    }
    int min_d = *std::min_element(dates.begin(), dates.end());
    int max_d = *std::max_element(dates.begin(), dates.end());
    if (max_d - min_d > 30) return false;

    // 3. No smoker/non-smoker mismatch
    bool has_smoker     = false;
    bool has_non_smoker = false;
    for (const auto& c : group) {
        if (c.smoking_preference == "smoker")     has_smoker     = true;
        if (c.smoking_preference == "non_smoker") has_non_smoker = true;
    }
    if (has_smoker && has_non_smoker) return false;

    return true;
}

// ── Main match function ───────────────────────────────────────────────────────
//
// We enumerate combinations of size `capacity` from the candidates list.
// This mirrors how the LOB iterates through all resting orders at a price level
// when matching a market order.  For hackathon scale (≤50 candidates, capacity
// ≤4) the O(C(50,4)) = 230,300 iterations are trivial.

MatchResult HousingMatcher::match(const MatchRequest& req) const {
    MatchResult result;
    const auto& cands = req.candidates;
    int n = static_cast<int>(cands.size());
    int k = req.capacity;

    if (k <= 0 || k > n) {
        result.error = "capacity must be between 1 and candidate count";
        return result;
    }

    // Priority queue: (score, group_index) — higher score = higher priority
    // Mirrors the LOB bid-side std::map<int,queue> where higher price = top entry
    using ScoredGroup = std::pair<double, std::vector<Candidate>>;
    auto cmp = [](const ScoredGroup& a, const ScoredGroup& b) {
        return a.first < b.first; // max-heap
    };
    std::priority_queue<ScoredGroup, std::vector<ScoredGroup>, decltype(cmp)> pq(cmp);

    // Enumerate all combinations of size k
    std::vector<int> indices(k);
    std::iota(indices.begin(), indices.end(), 0);

    while (true) {
        // Build group from current indices
        std::vector<Candidate> group;
        group.reserve(k);
        for (int idx : indices) group.push_back(cands[idx]);

        // Apply hard constraints (filter — equivalent to order validation)
        if (is_compatible(group, req.per_person_rent_cents)) {
            double s = score_group(group, req.per_person_rent_cents);
            pq.push({s, group});
        }

        // Advance to next combination (standard combinatorial iteration)
        int i = k - 1;
        while (i >= 0 && indices[i] == n - k + i) i--;
        if (i < 0) break;
        indices[i]++;
        for (int j = i+1; j < k; j++) indices[j] = indices[j-1] + 1;
    }

    // Extract top-3 (mirrors "take top-N price levels from book snapshot")
    int taken = 0;
    while (!pq.empty() && taken < 3) {
        auto [score, members] = pq.top();
        pq.pop();

        // Build explanation
        std::ostringstream exp;
        exp << "Score=" << static_cast<int>(score) << "; members: ";
        for (size_t mi = 0; mi < members.size(); mi++) {
            if (mi > 0) exp << ", ";
            exp << members[mi].display_name;
            int slack = members[mi].max_budget - req.per_person_rent_cents;
            exp << "(+$" << (slack/100) << " budget slack)";
        }
        result.groups.push_back({members, score, exp.str()});
        taken++;
    }

    return result;
}

} // namespace fairsplit

// ── Stdin/stdout protocol (READY / MATCH / QUIT) ──────────────────────────────

int main() {
    std::cout << "READY" << std::endl;
    std::string line;
    while (std::getline(std::cin, line)) {
        line.erase(0, line.find_first_not_of(" \t\r\n"));
        if (line.empty()) continue;

        if (line.rfind("MATCH", 0) == 0) {
            // Format: MATCH <capacity> <per_person_rent_cents> <json_array>
            std::istringstream iss(line.substr(5));
            int capacity = 0, rent = 0;
            iss >> capacity >> rent;
            // rest is json
            std::string json_part;
            std::getline(iss, json_part);
            json_part.erase(0, json_part.find_first_not_of(" \t"));

            auto candidates = fairsplit::parse_candidates_json(json_part);
            fairsplit::HousingMatcher matcher;
            fairsplit::MatchRequest req{capacity, rent, candidates};
            auto result = matcher.match(req);

            if (!result.error.empty()) {
                std::cout << "ERROR " << result.error << std::endl;
            } else {
                std::cout << "RESULT " << fairsplit::serialize_groups_json(result.groups)
                          << std::endl;
                std::cout << "OK" << std::endl;
            }
        } else if (line == "QUIT" || line == "EXIT") {
            break;
        } else {
            std::cout << "ERROR unknown command" << std::endl;
        }
        std::cout.flush();
    }
    return 0;
}
