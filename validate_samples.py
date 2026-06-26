import json
import requests
import sys
sys.path.insert(0, '.')  # Ensure app module can be imported
from app.utils.safety import validate_safety

API_URL = "http://localhost:8000/analyze-ticket"

def load_samples(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['cases']

def test_one(case):
    print(f"\n--- {case['id']}: {case['label']} ---")
    input_data = case['input']
    expected = case['expected_output']

    try:
        resp = requests.post(API_URL, json=input_data, timeout=30)
    except Exception as e:
        print(f"  ❌ Request failed: {e}")
        return False

    if resp.status_code != 200:
        print(f"  ❌ HTTP {resp.status_code}: {resp.text}")
        return False

    actual = resp.json()

    # Check required fields
    required_fields = ['ticket_id', 'relevant_transaction_id', 'evidence_verdict',
                       'case_type', 'severity', 'department', 'agent_summary',
                       'recommended_next_action', 'customer_reply', 'human_review_required']
    for f in required_fields:
        if f not in actual:
            print(f"  ❌ Missing field: {f}")
            return False

    # Compare critical fields
    passed = True
    for field in ['relevant_transaction_id', 'evidence_verdict', 'case_type', 'department', 'severity']:
        exp = expected.get(field)
        act = actual.get(field)
        if exp != act:
            print(f"  ❌ {field}: expected '{exp}', got '{act}'")
            passed = False

    # Check safety using the same logic as the service
    safety = validate_safety(actual['customer_reply'], actual['recommended_next_action'])
    if not safety['is_safe']:
        print(f"  ❌ Safety violations: {safety['violations']}")
        passed = False

    # Check human_review_required
    if actual['human_review_required'] != expected['human_review_required']:
        print(f"  ❌ human_review_required: expected {expected['human_review_required']}, got {actual['human_review_required']}")
        passed = False

    # Non‑empty strings
    for f in ['agent_summary', 'recommended_next_action']:
        if not isinstance(actual.get(f), str) or len(actual[f].strip()) == 0:
            print(f"  ❌ {f} is empty or not a string")
            passed = False

    if passed:
        print("  ✅ All checks passed.")
    else:
        print("  ❌ Some mismatches found.")
    return passed

def main():
    cases = load_samples('SUST_Preli_Sample_Cases.json')
    total = len(cases)
    passed_count = 0
    for case in cases:
        if test_one(case):
            passed_count += 1
    print(f"\nSummary: {passed_count}/{total} sample cases passed.")

if __name__ == "__main__":
    main()