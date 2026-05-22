"""Snowflake Cortex Analyst REST client."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

log = logging.getLogger(__name__)

SEMANTIC_MODEL_PATH = Path(__file__).parent / "semantic_model.yaml"
CORTEX_API_PATH = "/api/v2/cortex/analyst/message"
LOW_CONFIDENCE_THRESHOLD = 0.7


@dataclass
class CortexResult:
    question: str
    sql: str
    df: pd.DataFrame
    confidence: float
    error: Optional[str] = None
    fallback: bool = False
    raw_response: dict = field(default_factory=dict)


class CortexAnalystClient:
    """REST client for Snowflake Cortex Analyst /analyst/message endpoint."""

    def __init__(
        self,
        account: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
        warehouse: Optional[str] = None,
    ) -> None:
        self.account = account or os.environ["SNOWFLAKE_ACCOUNT"]
        self.user = user or os.environ["SNOWFLAKE_USER"]
        self.password = password or os.environ["SNOWFLAKE_PASSWORD"]
        self.database = database or os.getenv("SNOWFLAKE_DATABASE", "FLEET_ANALYTICS")
        self.warehouse = warehouse or os.getenv("SNOWFLAKE_WAREHOUSE", "FLEET_WH")

        self.base_url = f"https://{self.account}.snowflakecomputing.com"
        self._session: Optional[requests.Session] = None
        self._token: Optional[str] = None

    # ── Authentication ────────────────────────────────────────────────────────

    def _get_session(self) -> requests.Session:
        if self._session is not None:
            return self._session

        session = requests.Session()
        login_url = f"{self.base_url}/session/v1/login-request"
        payload = {
            "data": {
                "LOGIN_NAME": self.user,
                "PASSWORD": self.password,
                "ACCOUNT_NAME": self.account,
            }
        }
        resp = session.post(
            login_url,
            json=payload,
            params={"warehouse": self.warehouse, "databaseName": self.database},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        if not body.get("success"):
            raise RuntimeError(f"Snowflake login failed: {body.get('message')}")

        self._token = body["data"]["token"]
        session.headers.update({"Authorization": f'Snowflake Token="{self._token}"'})
        self._session = session
        log.debug("Authenticated with Snowflake account %s", self.account)
        return session

    # ── Core method ───────────────────────────────────────────────────────────

    def ask(self, question: str) -> CortexResult:
        """Send a natural-language question to Cortex Analyst and return the result."""
        log.info("Cortex Analyst query: %s", question)

        semantic_model = SEMANTIC_MODEL_PATH.read_text(encoding="utf-8")
        payload = {
            "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
            "semantic_model": semantic_model,
        }

        try:
            session = self._get_session()
            resp = session.post(
                f"{self.base_url}{CORTEX_API_PATH}",
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=60,
            )
            resp.raise_for_status()
            body = resp.json()
        except requests.exceptions.HTTPError as exc:
            log.error("Cortex Analyst HTTP error: %s", exc)
            return self._fallback(question, str(exc))
        except requests.exceptions.RequestException as exc:
            log.error("Cortex Analyst request failed: %s", exc)
            return self._fallback(question, str(exc))

        return self._parse_response(question, body)

    # ── Response parsing ──────────────────────────────────────────────────────

    def _parse_response(self, question: str, body: dict) -> CortexResult:
        try:
            message = body.get("message", {})
            content = message.get("content", [])

            sql_text = ""
            confidence = 1.0

            for block in content:
                if block.get("type") == "sql":
                    sql_text = block.get("statement", "")
                if block.get("type") == "confidence":
                    confidence = float(block.get("score", 1.0))

            if not sql_text:
                return self._fallback(question, "Cortex returned no SQL statement", body)

            if confidence < LOW_CONFIDENCE_THRESHOLD:
                log.warning(
                    "Low confidence (%.2f) for question: %s — returning fallback", confidence, question
                )
                return CortexResult(
                    question=question,
                    sql=sql_text,
                    df=pd.DataFrame(),
                    confidence=confidence,
                    fallback=True,
                    error=(
                        f"Confidence {confidence:.0%} is below threshold "
                        f"({LOW_CONFIDENCE_THRESHOLD:.0%}). Please rephrase your question."
                    ),
                    raw_response=body,
                )

            df = self._execute_sql(sql_text)
            return CortexResult(
                question=question,
                sql=sql_text,
                df=df,
                confidence=confidence,
                raw_response=body,
            )

        except Exception as exc:  # pylint: disable=broad-except
            log.exception("Error parsing Cortex response")
            return self._fallback(question, str(exc), body)

    def _execute_sql(self, sql: str) -> pd.DataFrame:
        """Execute the generated SQL via the Snowflake SQL API."""
        url = f"{self.base_url}/api/v2/statements"
        payload = {
            "statement": sql,
            "database": self.database,
            "warehouse": self.warehouse,
            "timeout": 60,
        }
        session = self._get_session()
        resp = session.post(url, json=payload, timeout=90)
        resp.raise_for_status()
        body = resp.json()

        # Handle async execution
        statement_handle = body.get("statementHandle", "")
        status = body.get("status", "")
        import time

        for _ in range(30):
            if status in ("success", "failed"):
                break
            time.sleep(2)
            poll_resp = session.get(f"{url}/{statement_handle}", timeout=30)
            poll_resp.raise_for_status()
            body = poll_resp.json()
            status = body.get("status", "")

        if status != "success":
            raise RuntimeError(f"SQL execution failed: {body.get('message', status)}")

        result_set = body.get("data", [])
        columns = [col["name"] for col in body.get("resultSetMetaData", {}).get("rowType", [])]
        return pd.DataFrame(result_set, columns=columns)

    @staticmethod
    def _fallback(question: str, reason: str, raw: dict = None) -> CortexResult:
        return CortexResult(
            question=question,
            sql="",
            df=pd.DataFrame(),
            confidence=0.0,
            fallback=True,
            error=f"Could not answer: {reason}",
            raw_response=raw or {},
        )
