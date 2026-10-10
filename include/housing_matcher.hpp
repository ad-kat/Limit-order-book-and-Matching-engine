#pragma once
/**
 * housing_matcher.hpp — FairSplit Housing Compatibility Matcher
 *
 * Conceptual reuse from OrderBook:
 *   - The OrderBook ranks orders by price priority using a priority_queue
 *     (best bid = highest price first; best ask = lowest price first).
 *   - Here we rank candidate roommate groups by a composite "budget-fit score"
 *     using the same priority-queue concept: the group with the HIGHEST score
 *     floats to the top, mirroring how the best bid floats to the top of the
 *     bid side.
 *   - Budget slack maps to "price headroom" — just as a buyer bidding above
 *     the ask gets filled first, a candidate with more budget slack above the
 *     per-person rent is ranked higher.
 *   - Date-overlap score maps to "time priority" — earlier/tighter date match
 *     is a tiebreaker, analogous to timestamp priority in FIFO within a price level.
 */

#include <string>
#include <vector>
#include <optional>

namespace fairsplit {

// ── Data structures ───────────────────────────────────────────────────────────

struct Candidate {
    std::string id;
    std::string display_name;
    int         max_budget;           // cents per month (this person's share)
    std::string move_in_date;         // "YYYY-MM-DD"
    std::string smoking_preference;   // "non_smoker" | "smoker" | "no_preference"
    int         preferred_roommate_count;
};

struct RoommateGroup {
    std::vector<Candidate> members;
    double score;                     // higher is better (mirrors LOB price priority)
    std::string explanation;
};

struct MatchRequest {
    int capacity;                     // number of bedrooms
    int per_person_rent_cents;        // monthly_rent / bedrooms (rounded up)
    std::vector<Candidate> candidates;
};

struct MatchResult {
    std::vector<RoommateGroup> groups; // up to 3, sorted by score desc
    std::string error;
};

// ── Matcher interface ─────────────────────────────────────────────────────────

class HousingMatcher {
public:
    HousingMatcher() = default;

    /**
     * Find the top-3 compatible roommate groups from candidates.
     *
     * Filtering (hard constraints — equivalent to order price validation):
     *   1. Candidate max_budget >= per_person_rent_cents
     *   2. Move-in dates within 30 days of each other
     *   3. Lifestyle compatibility: no smoker/non-smoker mismatches
     *   4. Group size == capacity
     *
     * Scoring (soft ranking — mirrors LOB price-priority ranking):
     *   score = sum_over_members(budget_slack + date_overlap_score + compatibility_bonus)
     *
     *   budget_slack        = (max_budget - per_person_rent_cents) / per_person_rent_cents * 100
     *   date_overlap_score  = max(0, 30 - max_date_spread_days) (tighter window = higher score)
     *   compatibility_bonus = 10 if all members share smoking preference, else 0
     */
    MatchResult match(const MatchRequest& req) const;

private:
    // Parse "YYYY-MM-DD" to days-since-epoch for comparison
    static int parse_date_to_days(const std::string& date);

    // Score a candidate group
    static double score_group(const std::vector<Candidate>& group,
                               int per_person_rent_cents);

    // Check if a set of candidates is compatible (hard constraints)
    static bool is_compatible(const std::vector<Candidate>& group,
                               int per_person_rent_cents);
};

// ── JSON helpers (used by main stdin protocol) ────────────────────────────────

/**
 * Parse JSON array of candidate objects.
 * Expected format: [{"id":"...","display_name":"...","max_budget":int,
 *                    "move_in_date":"YYYY-MM-DD","smoking_preference":"...",
 *                    "preferred_roommate_count":int}, ...]
 */
std::vector<Candidate> parse_candidates_json(const std::string& json);

/**
 * Serialize match result groups to JSON array string.
 */
std::string serialize_groups_json(const std::vector<RoommateGroup>& groups);

} // namespace fairsplit
