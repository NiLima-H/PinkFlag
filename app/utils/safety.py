import re

# Patterns that REQUEST credentials (forbidden)
REQUEST_PATTERNS = [
    r'(?:please|kindly|can you|would you)\s*(?:share|provide|give|enter|type|tell me)\s*(?:your\s*)?(?:pin|otp|password|passcode)',
    r'share\s+(?:your\s*)?(?:pin|otp|password)',
    r'provide\s+(?:your\s*)?(?:pin|otp|password)',
    r'enter\s+(?:your\s*)?(?:pin|otp|password)',
    r'confirm\s+(?:your\s*)?(?:pin|otp|password)',
]

REFUND_CONFIRM_PATTERNS = [
    r'\bwe (?:will|are going to) refund you\b',
    r'\bwe (?:have|will) (?:processed|process) (?:your )?refund\b',
    r'\brefund (?:has been|will be) (?:processed|credited)\b',
    r'\byour money (?:will be|is being) returned\b',
    r'\bwe (?:have|will) reversed?\b',
]

THIRD_PARTY_PATTERNS = [
    r'contact (?:this number|the number) [0-9]{10,}',
    r'call [0-9]{10,}',
    r'whatsapp [0-9]{10,}',
    r'send (?:money|tk|taka) to [0-9]{10,}',
]

def contains_pattern(text, patterns):
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

def validate_safety(customer_reply, recommended_next_action):
    violations = []
    combined = customer_reply + " " + recommended_next_action
    lower_combined = combined.lower()

    # Skip credential request check if the text is a WARNING (e.g., "do not share your PIN")
    # This prevents false positives for safety warnings.
    if not ("do not share" in lower_combined or "never share" in lower_combined):
        if contains_pattern(combined, REQUEST_PATTERNS):
            violations.append("credential_request")

    if contains_pattern(combined, REFUND_CONFIRM_PATTERNS):
        violations.append("unauthorized_refund")
    if contains_pattern(combined, THIRD_PARTY_PATTERNS):
        violations.append("suspicious_third_party")

    return {
        "is_safe": len(violations) == 0,
        "violations": violations
    }