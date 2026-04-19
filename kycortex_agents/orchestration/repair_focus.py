from typing import Any, Optional

from kycortex_agents.orchestration.repair_analysis import (
    dataclass_default_order_repair_examples,
    duplicate_constructor_argument_call_hint,
    duplicate_constructor_argument_details,
    duplicate_constructor_explicit_rewrite_hint,
    internal_constructor_strictness_details,
    missing_import_nameerror_details,
    missing_object_attribute_details,
    nested_payload_wrapper_field_validation_details,
    plain_class_field_default_factory_details,
)
from kycortex_agents.orchestration.repair_code_validation import (
    build_code_validation_repair_lines,
)
from kycortex_agents.orchestration.repair_signals import (
    implementation_prefers_direct_datetime_import,
    implementation_required_evidence_items,
    validation_summary_has_missing_datetime_import_issue,
    validation_summary_has_required_evidence_runtime_issue,
)
from kycortex_agents.orchestration.repair_test_validation import (
    build_test_validation_repair_lines,
)
from kycortex_agents.types import FailureCategory


def build_repair_focus_lines(
    repair_context: dict[str, Any],
    context: Optional[dict[str, Any]] = None,
) -> list[str]:
    failure_category = repair_context.get("failure_category")
    validation_summary = repair_context.get("validation_summary")
    if not isinstance(validation_summary, str) or not validation_summary.strip():
        return []

    failed_artifact_content = repair_context.get("failed_artifact_content")
    failed_content_lower = (
        failed_artifact_content.lower()
        if isinstance(failed_artifact_content, str)
        else ""
    )
    implementation_code = context.get("code", "") if isinstance(context, dict) else ""

    if failure_category == FailureCategory.CODE_VALIDATION.value:
        return build_code_validation_repair_lines(
            validation_summary.lower(),
            failed_content_lower,
            dataclass_default_order_repair_examples(failed_artifact_content),
            duplicate_constructor_argument_details(validation_summary),
            duplicate_constructor_argument_call_hint(
                validation_summary,
                failed_artifact_content,
            ),
            duplicate_constructor_explicit_rewrite_hint(
                validation_summary,
                failed_artifact_content,
            ),
            missing_object_attribute_details(
                validation_summary,
                failed_artifact_content,
            ),
            nested_payload_wrapper_field_validation_details(
                validation_summary,
                failed_artifact_content,
            ),
            internal_constructor_strictness_details(
                validation_summary,
                failed_artifact_content,
            ),
            plain_class_field_default_factory_details(
                validation_summary,
                failed_artifact_content,
            ),
            missing_import_nameerror_details(
                validation_summary,
                failed_artifact_content,
            ),
        )

    if failure_category != FailureCategory.TEST_VALIDATION.value:
        return []

    return build_test_validation_repair_lines(
        validation_summary,
        failed_artifact_content,
        implementation_code,
        repair_context.get("helper_surface_symbols"),
        repair_context.get("helper_surface_usages"),
        validation_summary_has_missing_datetime_import_issue(
            validation_summary,
            failed_artifact_content,
        ),
        validation_summary_has_required_evidence_runtime_issue(
            validation_summary,
            failed_artifact_content,
            implementation_code,
        ),
        implementation_required_evidence_items(implementation_code),
        implementation_prefers_direct_datetime_import(implementation_code),
    )


__all__ = ["build_repair_focus_lines"]