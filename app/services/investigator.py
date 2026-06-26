import re
from typing import Optional, List
from app.models import (
    AnalyzeTicketRequest, AnalyzeTicketResponse,
    EvidenceVerdict, CaseType, Department, Severity,
    TransactionEntry
)
from app.utils.safety import validate_safety

# Bangla digit → ASCII digit mapping
BANGLA_DIGIT_MAP = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def normalize_digits(text: str) -> str:
    """Convert Bangla/Bengali digits to ASCII digits for amount extraction."""
    return text.translate(BANGLA_DIGIT_MAP)


class TicketInvestigator:
    def __init__(self, use_llm=False, llm_client=None):
        self.use_llm = use_llm
        self.llm_client = llm_client

    def investigate(self, request: AnalyzeTicketRequest) -> AnalyzeTicketResponse:
        # 1. Find relevant transaction
        relevant_txn = self._find_relevant_transaction(
            request.complaint, request.transaction_history
        )

        # 2. Determine evidence verdict
        evidence_verdict = self._determine_evidence_verdict(
            request.complaint, relevant_txn, request.transaction_history
        )

        # 3. Classify case type
        case_type = self._classify_case_type(
            request.complaint, relevant_txn, evidence_verdict, request.user_type
        )

        # 4. Determine department
        department = self._determine_department(case_type, evidence_verdict)

        # 5. Determine severity
        severity = self._determine_severity(case_type, evidence_verdict, relevant_txn)

        # 6. Generate responses
        agent_summary, recommended_action, customer_reply = self._generate_responses(
            request, relevant_txn, evidence_verdict, case_type
        )

        # 7. Validate safety and fix if needed
        safety_check = validate_safety(customer_reply, recommended_action)
        if not safety_check["is_safe"]:
            customer_reply = self._apply_safety_fixes(customer_reply)
            recommended_action = self._apply_safety_fixes(recommended_action)

        # 8. Human review?
        human_review_required = self._should_review_human(
            case_type, evidence_verdict, severity, safety_check
        )

        # 9. Confidence and reason codes
        confidence = self._estimate_confidence(relevant_txn, evidence_verdict, case_type)
        reason_codes = self._generate_reason_codes(relevant_txn, evidence_verdict, case_type)

        return AnalyzeTicketResponse(
            ticket_id=request.ticket_id,
            relevant_transaction_id=relevant_txn.transaction_id if relevant_txn else None,
            evidence_verdict=evidence_verdict,
            case_type=case_type,
            severity=severity,
            department=department,
            agent_summary=agent_summary,
            recommended_next_action=recommended_action,
            customer_reply=customer_reply,
            human_review_required=human_review_required,
            confidence=confidence,
            reason_codes=reason_codes
        )

    # ---------- Helper methods ----------

    def _find_relevant_transaction(self, complaint: str, history: List[TransactionEntry]) -> Optional[TransactionEntry]:
        if not history:
            return None

        complaint_lower = complaint.lower()
        # Normalize Bangla digits so amounts like ২০০০ → 2000 are found
        complaint_normalized = normalize_digits(complaint_lower)

        # 1. Explicit transaction ID mention
        txn_id_match = re.search(r'(TXN-[0-9]+)', complaint, re.IGNORECASE)
        if txn_id_match:
            mentioned_id = txn_id_match.group(1).upper()
            for txn in history:
                if txn.transaction_id.upper() == mentioned_id:
                    return txn

        # 2. Extract all amounts from complaint (handles Bangla numerals too)
        amounts = [
            int(x) for x in re.findall(r'(\d+)[\s,.]*(?:taka|tk|bdt|টাকা)?', complaint_normalized)
            if int(x) > 0
        ]

        # 3. Check for duplicate payment scenario: two identical transactions exist
        #    → return the second (most recent) one as the suspected duplicate
        if any(k in complaint_normalized for k in ['twice', 'double', 'duplicate', 'দুবার', 'ডুপ্লিকেট']):
            if amounts:
                amt = amounts[0]
                dupes = sorted(
                    [t for t in history if int(t.amount) == amt],
                    key=lambda x: x.timestamp
                )
                if len(dupes) >= 2:
                    return dupes[-1]  # second / most recent = suspected duplicate

        # 4. Ambiguity check: if multiple transactions match the same amount and type,
        #    do NOT guess — signal ambiguity by returning None so caller gets INSUFFICIENT_DATA
        if amounts:
            for amt in amounts:
                candidates = [
                    t for t in history
                    if int(t.amount) == amt and t.status in ('completed', 'pending', 'failed')
                ]
                if len(candidates) >= 2:
                    # Check if they're plausibly all of the same type (same day, same type)
                    # If so, this is genuinely ambiguous — return None
                    distinct_counterparties = {t.counterparty for t in candidates}
                    if len(distinct_counterparties) > 1 and len(candidates) >= 2:
                        # Multiple txns, different recipients — cannot determine which one
                        return None

        # 5. Amount-based matching (single clear match)
        type_keywords = {
            'transfer': ['transfer', 'send', 'sent', 'ট্রান্সফার', 'পাঠিয়েছি'],
            'payment': ['pay', 'payment', 'paid', 'পেমেন্ট'],
            'cash_in': ['cash', 'deposit', 'ক্যাশ', 'ক্যাশ ইন'],
            'cash_out': ['cash out', 'withdraw', 'উইথড্র'],
            'settlement': ['settlement', 'settle', 'সেটেলমেন্ট'],
        }

        if amounts:
            for amt in amounts:
                # Match across all statuses (not just completed) — pending txns matter too
                candidates = [t for t in history if int(t.amount) == amt]
                if not candidates:
                    continue

                # Prefer type-matched candidate
                best = None
                for t in candidates:
                    for t_type, keywords in type_keywords.items():
                        if any(k in complaint_normalized for k in keywords) and t.type == t_type:
                            best = t
                            break
                    if best:
                        break

                if best:
                    return best

                # Among candidates, prefer: pending > failed > completed (most informative status first)
                for preferred_status in ('pending', 'failed', 'completed'):
                    status_match = [t for t in candidates if t.status == preferred_status]
                    if status_match:
                        return max(status_match, key=lambda x: x.timestamp)

        # 6. No amount in complaint and no txn ID — vague complaint, return None
        if not amounts and not txn_id_match:
            return None

        # 7. Fallback: type keyword match only (no amount specified)
        for t_type, keywords in type_keywords.items():
            if any(k in complaint_normalized for k in keywords):
                matching = [t for t in history if t.type == t_type]
                if len(matching) == 1:
                    return matching[0]
                if matching:
                    return max(matching, key=lambda x: x.timestamp)

        # 8. Last resort: most recent transaction in history
        if history:
            return max(history, key=lambda x: x.timestamp)

        return None

    def _determine_evidence_verdict(self, complaint: str, txn: Optional[TransactionEntry],
                                    history: List[TransactionEntry]) -> EvidenceVerdict:
        if not txn:
            return EvidenceVerdict.INSUFFICIENT_DATA

        complaint_lower = complaint.lower()
        complaint_normalized = normalize_digits(complaint_lower)
        status = txn.status

        # Contradiction: customer says "failed" but txn is completed
        if 'failed' in complaint_normalized and status == 'completed':
            return EvidenceVerdict.INCONSISTENT

        # Contradiction: customer says success/received but txn is failed
        if any(k in complaint_normalized for k in ('success', 'received', 'পেয়েছি')) and status == 'failed':
            return EvidenceVerdict.INCONSISTENT

        # Wrong-transfer claim but history shows repeated prior transfers to same recipient
        # → suggests an established relationship, contradicting the "accident" claim
        if any(k in complaint_normalized for k in ('wrong', 'ভুল')) and txn.type == 'transfer':
            same_recipient = [
                t for t in history
                if t.type == 'transfer'
                and t.counterparty == txn.counterparty
                and t.transaction_id != txn.transaction_id
            ]
            if len(same_recipient) >= 2:
                return EvidenceVerdict.INCONSISTENT

        # Amount mismatch between complaint and matched transaction
        amounts = [
            int(x) for x in re.findall(r'(\d+)[\s,.]*(?:taka|tk|bdt|টাকা)?', complaint_normalized)
            if int(x) > 0
        ]
        if amounts and int(txn.amount) not in amounts:
            return EvidenceVerdict.INCONSISTENT

        return EvidenceVerdict.CONSISTENT

    def _classify_case_type(self, complaint: str, txn: Optional[TransactionEntry],
                            verdict: EvidenceVerdict, user_type: Optional[str]) -> CaseType:
        comp = complaint.lower()
        comp_norm = normalize_digits(comp)

        # Phishing / social engineering (English + Bangla)
        phishing_keywords = [
            'scam', 'fraud', 'phishing', 'otp', 'pin', 'password',
            'call from', 'suspicious', 'জাল', 'প্রতারণা', 'পিন', 'ওটিপি'
        ]
        if any(k in comp_norm for k in phishing_keywords):
            return CaseType.PHISHING_OR_SOCIAL_ENGINEERING

        # Duplicate payment
        if any(k in comp_norm for k in ['duplicate', 'twice', 'double', 'দুবার', 'ডুপ্লিকেট']):
            return CaseType.DUPLICATE_PAYMENT

        # Wrong transfer (before general "failed" check to avoid misclassification)
        wrong_transfer_keywords = [
            'wrong number', 'wrong person', 'wrong recipient', 'wrong transfer',
            'ভুল নম্বর', 'ভুল ট্রান্সফার', 'wrong'
        ]
        if any(k in comp_norm for k in wrong_transfer_keywords):
            return CaseType.WRONG_TRANSFER

        # Agent cash-in issue (English + Bangla)
        agent_keywords = ['agent', 'এজেন্ট']
        cashin_keywords = ['cash', 'ক্যাশ', 'deposit', 'ডিপোজিট', 'cash in', 'ক্যাশ ইন', 'balance', 'ব্যালেন্স']
        if any(k in comp_norm for k in agent_keywords) and any(k in comp_norm for k in cashin_keywords):
            return CaseType.AGENT_CASH_IN_ISSUE

        # Merchant settlement delay
        if user_type == 'merchant' or ('merchant' in comp_norm and 'settlement' in comp_norm):
            return CaseType.MERCHANT_SETTLEMENT_DELAY
        if 'settlement' in comp_norm and txn and txn.type == 'settlement':
            return CaseType.MERCHANT_SETTLEMENT_DELAY

        # Payment failed
        if any(k in comp_norm for k in ['failed', 'not go through', 'বিফল', 'didn\'t go']):
            return CaseType.PAYMENT_FAILED

        # Refund request
        if any(k in comp_norm for k in ['refund', 'ফেরত', 'return my money', 'money back', 'get back']):
            return CaseType.REFUND_REQUEST

        # Infer from transaction type when complaint is ambiguous
        if txn:
            if txn.type == 'transfer':
                return CaseType.WRONG_TRANSFER
            if txn.type == 'payment':
                if txn.status == 'failed':
                    return CaseType.PAYMENT_FAILED
                return CaseType.REFUND_REQUEST
            if txn.type == 'cash_in':
                return CaseType.AGENT_CASH_IN_ISSUE
            if txn.type == 'settlement':
                return CaseType.MERCHANT_SETTLEMENT_DELAY

        return CaseType.OTHER

    def _determine_department(self, case_type: CaseType, verdict: EvidenceVerdict) -> Department:
        mapping = {
            CaseType.WRONG_TRANSFER: Department.DISPUTE_RESOLUTION,
            CaseType.PAYMENT_FAILED: Department.PAYMENTS_OPS,
            CaseType.REFUND_REQUEST: (
                Department.CUSTOMER_SUPPORT
                if verdict == EvidenceVerdict.CONSISTENT
                else Department.DISPUTE_RESOLUTION
            ),
            CaseType.DUPLICATE_PAYMENT: Department.PAYMENTS_OPS,
            CaseType.MERCHANT_SETTLEMENT_DELAY: Department.MERCHANT_OPERATIONS,
            CaseType.AGENT_CASH_IN_ISSUE: Department.AGENT_OPERATIONS,
            CaseType.PHISHING_OR_SOCIAL_ENGINEERING: Department.FRAUD_RISK,
            CaseType.OTHER: Department.CUSTOMER_SUPPORT,
        }
        return mapping.get(case_type, Department.CUSTOMER_SUPPORT)

    def _determine_severity(self, case_type: CaseType, verdict: EvidenceVerdict,
                            txn: Optional[TransactionEntry]) -> Severity:
        if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
            return Severity.CRITICAL

        if case_type == CaseType.WRONG_TRANSFER:
            # Inconsistent evidence (e.g. established recipient) → MEDIUM
            if verdict == EvidenceVerdict.INCONSISTENT:
                return Severity.MEDIUM
            return Severity.HIGH

        if case_type == CaseType.DUPLICATE_PAYMENT:
            # Consistent duplicate evidence → HIGH; inconsistent/no txn → MEDIUM
            if verdict == EvidenceVerdict.CONSISTENT:
                return Severity.HIGH
            return Severity.MEDIUM

        if case_type == CaseType.AGENT_CASH_IN_ISSUE:
            return Severity.HIGH

        if case_type == CaseType.PAYMENT_FAILED:
            if txn and txn.amount >= 1000:
                return Severity.HIGH
            return Severity.MEDIUM

        if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
            return Severity.MEDIUM

        if case_type == CaseType.REFUND_REQUEST:
            return Severity.LOW

        # OTHER or vague
        if verdict == EvidenceVerdict.INSUFFICIENT_DATA:
            return Severity.LOW

        return Severity.LOW

    def _generate_responses(self, request, txn, verdict, case_type):
        complaint_lower = request.complaint.lower()
        is_bangla = getattr(request, 'language', 'en') == 'bn' or (
            any(ord(c) > 0x0980 for c in request.complaint)
        )
        txn_id = txn.transaction_id if txn else None
        txn_ref = f"transaction {txn_id}" if txn_id else "the reported transaction"

        # ── Agent summary ──────────────────────────────────────────────────────
        if txn:
            summary = (
                f"Customer reports issue with transaction {txn_id} "
                f"({int(txn.amount)} BDT). "
            )
        else:
            summary = f"Customer reports: {request.complaint[:120]}. "

        if verdict == EvidenceVerdict.CONSISTENT:
            summary += "Transaction data supports the complaint."
        elif verdict == EvidenceVerdict.INCONSISTENT:
            summary += "Transaction data contradicts the complaint."
        else:
            summary += "Insufficient transaction data to verify."

        # Enrich summary for key case types
        if case_type == CaseType.WRONG_TRANSFER and txn:
            if verdict == EvidenceVerdict.INCONSISTENT:
                summary = (
                    f"Customer claims {txn_id} ({int(txn.amount)} BDT to "
                    f"{txn.counterparty}) was a wrong transfer, but transaction "
                    f"history shows prior transfers to the same counterparty, "
                    f"suggesting an established recipient."
                )
            else:
                summary = (
                    f"Customer reports sending {int(txn.amount)} BDT via {txn_id} "
                    f"to {txn.counterparty}, which they believe was the wrong "
                    f"recipient."
                )

        elif case_type == CaseType.DUPLICATE_PAYMENT and txn:
            summary = (
                f"Customer reports a possible duplicate payment. "
                f"Transaction {txn_id} ({int(txn.amount)} BDT) appears to be a "
                f"duplicate of an earlier identical payment."
            )

        elif case_type == CaseType.PAYMENT_FAILED and txn:
            summary = (
                f"Customer attempted a {int(txn.amount)} BDT payment ({txn_id}) "
                f"which shows as failed, but reports balance may have been deducted. "
                f"Requires payments operations investigation."
            )

        elif case_type == CaseType.AGENT_CASH_IN_ISSUE and txn:
            summary = (
                f"Customer reports {int(txn.amount)} BDT cash-in via "
                f"{txn.counterparty} ({txn_id}) not reflected in balance. "
                f"Transaction status is {txn.status}."
            )

        elif case_type == CaseType.MERCHANT_SETTLEMENT_DELAY and txn:
            summary = (
                f"Merchant reports settlement delay for {txn_id} "
                f"({int(txn.amount)} BDT). Settlement status is {txn.status}."
            )

        elif case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
            summary = (
                "Customer reports an unsolicited contact asking for credentials "
                "(PIN/OTP/password). Likely social engineering attempt. "
                "No transaction involved."
            )

        elif case_type == CaseType.OTHER and not txn:
            summary = (
                "Customer reports a vague concern without specifying a transaction, "
                "amount, or clear issue. Insufficient detail to identify any relevant "
                "transaction."
            )

        # ── Recommended action ─────────────────────────────────────────────────
        action_map = {
            CaseType.WRONG_TRANSFER: (
                f"Verify {txn_ref} details with the customer and initiate the "
                f"wrong-transfer dispute workflow per policy."
                if verdict != EvidenceVerdict.INCONSISTENT
                else
                f"Flag for human review. Verify with the customer whether this was "
                f"genuinely a wrong transfer given the established transaction pattern "
                f"with this recipient."
            ),
            CaseType.PAYMENT_FAILED: (
                f"Investigate {txn_ref} ledger status. If balance was deducted on a "
                f"failed payment, initiate the automatic reversal flow within standard SLA."
            ),
            CaseType.REFUND_REQUEST: (
                "Inform the customer that refund eligibility depends on the merchant's "
                "own policy. Provide guidance on contacting the merchant directly for a refund."
            ),
            CaseType.DUPLICATE_PAYMENT: (
                f"Verify the duplicate with payments_ops. If the biller confirms only "
                f"one payment was received, initiate reversal of {txn_id}."
                if txn_id else
                "Investigate potential duplicate charge and reverse through proper channels after verification."
            ),
            CaseType.MERCHANT_SETTLEMENT_DELAY: (
                f"Route to merchant_operations to verify settlement batch status. "
                f"If the batch is delayed, communicate a revised ETA to the merchant."
            ),
            CaseType.AGENT_CASH_IN_ISSUE: (
                f"Investigate {txn_ref} pending status with agent operations. "
                f"Confirm settlement state and resolve within the standard cash-in SLA."
            ),
            CaseType.PHISHING_OR_SOCIAL_ENGINEERING: (
                "Escalate to fraud_risk team immediately. Confirm to customer that the "
                "company never asks for OTP. Log the reported number for fraud pattern analysis."
            ),
            CaseType.OTHER: (
                "Reply to customer asking for specific details: which transaction, "
                "what amount, what went wrong, and approximate time."
            ),
        }
        recommended_action = action_map.get(
            case_type,
            "Review case details and follow standard procedure."
        )

        # ── Customer reply ─────────────────────────────────────────────────────
        # Bangla replies for Bangla-language inputs
        if is_bangla and case_type == CaseType.AGENT_CASH_IN_ISSUE:
            if txn_id:
                customer_reply = (
                    f"আপনার লেনদেন {txn_id} এর বিষয়ে আমরা অবগত হয়েছি। "
                    "আমাদের এজেন্ট অপারেশন্স দল এটি দ্রুত যাচাই করবে এবং "
                    "অফিসিয়াল চ্যানেলে আপনাকে জানাবে। "
                    "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"
                )
            else:
                customer_reply = (
                    "আপনার ক্যাশ ইন সংক্রান্ত সমস্যা আমরা দেখছি। "
                    "আমাদের এজেন্ট অপারেশন টিম এটি যাচাই করবে এবং "
                    "অফিসিয়াল চ্যানেলে আপনাকে জানাবে। "
                    "অনুগ্রহ করে পিন বা ওটিপি শেয়ার করবেন না।"
                )
        elif case_type == CaseType.WRONG_TRANSFER:
            ref = f"about transaction {txn_id}" if txn_id else "about your transaction"
            customer_reply = (
                f"We have noted your concern {ref}. "
                "Please do not share your PIN or OTP with anyone. "
                "Our dispute team will review the case and contact you through "
                "official support channels."
            )
        elif case_type == CaseType.PAYMENT_FAILED:
            ref = f"that transaction {txn_id} may have caused" if txn_id else "that there may have been"
            customer_reply = (
                f"We have noted {ref} an unexpected balance deduction. "
                "Our payments team will review the case and any eligible amount "
                "will be returned through official channels. "
                "Please do not share your PIN or OTP with anyone."
            )
        elif case_type == CaseType.REFUND_REQUEST:
            customer_reply = (
                "Thank you for reaching out. Refunds for completed merchant payments "
                "depend on the merchant's own policy. We recommend contacting the "
                "merchant directly. If you need help reaching them, please reply and "
                "we will guide you. Please do not share your PIN or OTP with anyone."
            )
        elif case_type == CaseType.DUPLICATE_PAYMENT:
            ref = f"for transaction {txn_id}" if txn_id else "for this payment"
            customer_reply = (
                f"We have noted the possible duplicate payment {ref}. "
                "Our payments team will verify with the biller and any eligible "
                "amount will be returned through official channels. "
                "Please do not share your PIN or OTP with anyone."
            )
        elif case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
            ref = f"about settlement {txn_id}" if txn_id else "about the settlement delay"
            customer_reply = (
                f"We have noted your concern {ref}. "
                "Our merchant operations team will check the batch status and update "
                "you on the expected settlement time through official channels."
            )
        elif case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
            customer_reply = (
                "Thank you for reaching out before sharing any information. "
                "We never ask for your PIN, OTP, or password under any circumstances. "
                "Please do not share these with anyone, even if they claim to be from us. "
                "Our fraud team has been notified of this incident."
            )
        elif case_type == CaseType.OTHER and verdict == EvidenceVerdict.INSUFFICIENT_DATA:
            # Check if ambiguous-match scenario (multiple txns, can't determine which)
            if txn is None and request.transaction_history:
                # Check for ambiguous multi-match
                amounts = [
                    int(x) for x in re.findall(
                        r'(\d+)[\s,.]*(?:taka|tk|bdt|টাকা)?',
                        normalize_digits(request.complaint.lower())
                    )
                    if int(x) > 0
                ]
                if amounts:
                    customer_reply = (
                        "Thank you for reaching out. We see multiple transactions "
                        f"of {amounts[0]} BDT on that date. Could you share your "
                        "recipient's number so we can identify the right transaction? "
                        "Please do not share your PIN or OTP with anyone."
                    )
                else:
                    customer_reply = (
                        "Thank you for reaching out. To help you faster, please share "
                        "the transaction ID, the amount involved, and a short description "
                        "of what went wrong. Please do not share your PIN or OTP with anyone."
                    )
            else:
                customer_reply = (
                    "Thank you for reaching out. To help you faster, please share the "
                    "transaction ID, the amount involved, and a short description of what "
                    "went wrong. Please do not share your PIN or OTP with anyone."
                )
        else:
            customer_reply = (
                "Thank you for reaching out to us. We are looking into your concern "
                "and will get back to you through official channels as soon as possible."
            )

        return summary, recommended_action, customer_reply

    def _should_review_human(self, case_type, verdict, severity, safety_check):
        # Clear auto-resolvable paths: consistent payment failure → no human needed
        if case_type == CaseType.PAYMENT_FAILED and verdict == EvidenceVerdict.CONSISTENT:
            return False
        # Refund with consistent evidence → customer_support can handle
        if case_type == CaseType.REFUND_REQUEST and verdict == EvidenceVerdict.CONSISTENT:
            return False
        # Merchant settlement with consistent evidence → merchant_ops handles automatically
        if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY and verdict == EvidenceVerdict.CONSISTENT:
            return False
        # Vague / other with no transaction → just ask for more info, no escalation
        if case_type == CaseType.OTHER and verdict == EvidenceVerdict.INSUFFICIENT_DATA:
            return False
        # Ambiguous multi-match → ask for clarification, no escalation yet
        if verdict == EvidenceVerdict.INSUFFICIENT_DATA and case_type == CaseType.WRONG_TRANSFER:
            return False

        # Always escalate these
        if case_type in (
            CaseType.PHISHING_OR_SOCIAL_ENGINEERING,
            CaseType.WRONG_TRANSFER,
            CaseType.DUPLICATE_PAYMENT,
            CaseType.AGENT_CASH_IN_ISSUE,
        ):
            return True

        # Escalate on inconsistent evidence (possible fraud or data mismatch)
        if verdict == EvidenceVerdict.INCONSISTENT:
            return True

        # Escalate on high/critical severity
        if severity in (Severity.CRITICAL, Severity.HIGH):
            return True

        # Escalate if safety rules were violated
        if not safety_check["is_safe"]:
            return True

        return False

    def _estimate_confidence(self, txn, verdict, case_type):
        if not txn:
            # Phishing needs no txn and is still high confidence
            if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
                return 0.95
            # Ambiguous multi-match or vague complaint
            return 0.6
        if verdict == EvidenceVerdict.CONSISTENT:
            if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
                return 0.92
            if case_type == CaseType.DUPLICATE_PAYMENT:
                return 0.93
            if case_type == CaseType.AGENT_CASH_IN_ISSUE:
                return 0.88
            return 0.9
        elif verdict == EvidenceVerdict.INCONSISTENT:
            return 0.75
        else:
            return 0.65

    def _generate_reason_codes(self, txn, verdict, case_type):
        codes = [case_type.value]
        if txn:
            codes.append("transaction_match")
        # Case-specific enrichment codes
        enrichment = {
            CaseType.WRONG_TRANSFER: "dispute_initiated",
            CaseType.PAYMENT_FAILED: "potential_balance_deduction",
            CaseType.REFUND_REQUEST: "merchant_policy_dependent",
            CaseType.DUPLICATE_PAYMENT: "biller_verification_required",
            CaseType.MERCHANT_SETTLEMENT_DELAY: "delay",
            CaseType.AGENT_CASH_IN_ISSUE: "agent_ops",
            CaseType.PHISHING_OR_SOCIAL_ENGINEERING: "critical_escalation",
            CaseType.OTHER: "needs_clarification",
        }
        extra = enrichment.get(case_type)
        if extra:
            codes.append(extra)
        codes.append(verdict.value)
        return codes

    def _apply_safety_fixes(self, text):
        fixes = [
            (r'(?:please|kindly)\s*share\s*your\s*pin', 'Please do not share your PIN'),
            (r'provide\s*your\s*otp', 'Please do not share your OTP'),
            (r'we\s*will\s*refund\s*you', 'Any eligible amount will be returned through official channels'),
            (r'refund\s+(?:has been|will be)\s+(?:processed|credited)',
             'Any eligible amount will be returned through official channels'),
            (r'your money (?:will be|is being) returned',
             'Any eligible amount will be returned through official channels'),
        ]
        for pattern, replacement in fixes:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text