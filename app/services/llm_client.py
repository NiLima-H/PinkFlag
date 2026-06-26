import os
from typing import Optional
import json

class LLMClient:
    def __init__(self, provider: str = "openai"):
        self.provider = provider
        self.client = None
        self.setup_client()
    
    def setup_client(self):
        if self.provider == "openai":
            import openai
            openai.api_key = os.getenv("OPENAI_API_KEY")
            self.client = openai
        elif self.provider == "anthropic":
            import anthropic
            self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    def analyze(self, complaint: str, transaction_history: list) -> dict:
        """Send analysis to LLM and return structured response"""
        prompt = self._build_prompt(complaint, transaction_history)
        
        if self.provider == "openai":
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",  # or gpt-3.5-turbo
                messages=[
                    {"role": "system", "content": "You are a fintech support copilot. Analyze complaints and transaction data."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        
        return None
    
    def _build_prompt(self, complaint: str, history: list) -> str:
        return f"""
        Analyze this fintech complaint and transaction history:
        
        Complaint: {complaint}
        Transaction History: {json.dumps(history, indent=2)}
        
        Return JSON with:
        - relevant_transaction_id: the transaction ID this refers to
        - evidence_verdict: consistent/inconsistent/insufficient_data
        - case_type: one of wrong_transfer, payment_failed, refund_request, duplicate_payment, merchant_settlement_delay, agent_cash_in_issue, phishing_or_social_engineering, other
        - severity: low/medium/high/critical
        - department: customer_support/dispute_resolution/payments_ops/merchant_operations/agent_operations/fraud_risk
        - agent_summary: concise summary
        - recommended_next_action: operational step
        - customer_reply: safe official reply (NEVER ask for PIN/OTP/password)
        - human_review_required: boolean
        - confidence: 0-1 float
        """