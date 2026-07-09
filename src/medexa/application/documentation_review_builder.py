from __future__ import annotations

import uuid

from medexa.domain.documentation_review import DocumentationReviewItem, DocumentationReviewReport
from medexa.schemas import Alert, BillingSummary, SessionState


class DocumentationReviewBuilder:
    """Rules-derived documentation checklist — billing authority stays Path A."""

    def build(self, state: SessionState, billing_summary: BillingSummary) -> DocumentationReviewReport:
        items: list[DocumentationReviewItem] = []

        for alert in state.alerts:
            item = self._from_alert(state.session_id, alert)
            if item is not None:
                items.append(item)

        for line in billing_summary.line_items:
            if line.units == 0 and line.total_seconds > 0:
                items.append(
                    DocumentationReviewItem(
                        item_id=str(uuid.uuid4()),
                        category="units",
                        severity="warning",
                        title=f"Zero units for {line.cpt_code}",
                        detail=(
                            f"{line.display_name} has {line.total_seconds}s recorded "
                            "but 0 billable units under the 8-minute rule."
                        ),
                    )
                )

        if state.pre_auth_reconciliation is not None and not state.pre_auth_reconciliation.reconciled:
            items.append(
                DocumentationReviewItem(
                    item_id=str(uuid.uuid4()),
                    category="pre_auth",
                    severity="high",
                    title="Pre-authorization not reconciled",
                    detail="Open pre-auth violations remain at session end.",
                )
            )

        for hint in state.assistant_suggestions:
            if hint.status != "active":
                continue
            items.append(
                DocumentationReviewItem(
                    item_id=str(uuid.uuid4()),
                    category="assistant_hint",
                    severity="info",
                    title=hint.title,
                    detail=hint.body,
                )
            )

        if not state.transcript_text and not state.transcript_chunks:
            items.append(
                DocumentationReviewItem(
                    item_id=str(uuid.uuid4()),
                    category="documentation",
                    severity="warning",
                    title="Missing transcript",
                    detail="No transcript was captured before finalize.",
                )
            )

        return DocumentationReviewReport(
            session_id=state.session_id,
            items=items,
            open_count=sum(1 for item in items if not item.resolved),
        )

    @staticmethod
    def _from_alert(session_id: str, alert: Alert) -> DocumentationReviewItem | None:
        if alert.alert_type == "ncci_conflict":
            detail = alert.message
            if "Modifier 59" in alert.message or "modifier 59" in alert.message.lower():
                detail = f"{alert.message}. BEST BILLING PATH: Append Modifier 59 to override the bundling edit if the service was distinct and separate."
            else:
                detail = f"{alert.message}. BEST BILLING PATH: These codes bundle. Only the primary comprehensive code should be billed unless a modifier is medically justified."

            return DocumentationReviewItem(
                item_id=str(uuid.uuid4()),
                category="ncci",
                severity="high" if alert.severity == "high" else "warning",
                title="NCCI Bundling Conflict",
                detail=detail,
            )
        if alert.alert_type in {"pre_auth_required", "billing_conflict"}:
            return DocumentationReviewItem(
                item_id=str(uuid.uuid4()),
                category="pre_auth" if alert.alert_type == "pre_auth_required" else "billing",
                severity="high" if alert.severity == "high" else "warning",
                title=alert.alert_type.replace("_", " ").title(),
                detail=alert.message,
            )
        if alert.severity == "high":
            return DocumentationReviewItem(
                item_id=str(uuid.uuid4()),
                category="documentation",
                severity="warning",
                title=alert.alert_type.replace("_", " ").title(),
                detail=alert.message,
            )
        return None
