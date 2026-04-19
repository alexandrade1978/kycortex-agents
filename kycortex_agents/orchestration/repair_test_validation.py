from kycortex_agents.orchestration.repair_test_analysis import (
    analyze_test_repair_surface,
    normalized_helper_surface_symbols,
    validation_summary_symbols,
)
from kycortex_agents.orchestration.repair_test_runtime import (
    build_runtime_only_test_repair_lines,
)
from kycortex_agents.orchestration.repair_test_structure import (
    build_structural_test_repair_lines,
)


def build_test_validation_repair_lines(
    validation_summary: str,
    failed_artifact_content: object,
    implementation_code: str,
    helper_surface_symbols: object,
    helper_surface_usages: object,
    missing_datetime_import_issue: bool,
    required_evidence_runtime_issue: bool,
    required_evidence_items: list[str],
    implementation_prefers_direct_datetime_import: bool,
) -> list[str]:
    summary_lower = validation_summary.lower()
    failed_content_lower = (
        failed_artifact_content.lower()
        if isinstance(failed_artifact_content, str)
        else ""
    )

    lines: list[str] = []
    if "type mismatches:" in summary_lower and "type mismatches: none" not in summary_lower:
        lines.append(
            "PRIORITY: Fix type mismatches before other repairs. When the behavior contract specifies that a parameter must be of type dict, list, int, or another concrete type, every test fixture and call argument must use a value of exactly that type — not a string placeholder."
        )
        lines.append(
            "Replace string placeholders like details='details' with concrete typed values like details={'key': 'value'} when the contract requires dict. Match the exact type constraint from the behavior contract for every flagged parameter."
        )

    surface_analysis = analyze_test_repair_surface(
        validation_summary,
        implementation_code,
        failed_artifact_content,
    )

    normalized_helper_symbols = normalized_helper_surface_symbols(helper_surface_symbols)
    if not normalized_helper_symbols:
        normalized_helper_symbols = normalized_helper_surface_symbols(helper_surface_usages)
    assertionless_tests = validation_summary_symbols(
        validation_summary,
        "Tests without assertion-like checks",
    )

    lines.extend(
        build_structural_test_repair_lines(
            summary_lower,
            failed_content_lower,
            surface_analysis.imported_module_symbols,
            surface_analysis.undefined_available_module_symbols,
            surface_analysis.helper_alias_names,
            surface_analysis.unknown_module_symbols,
            normalized_helper_symbols,
            assertionless_tests,
            missing_datetime_import_issue,
            implementation_prefers_direct_datetime_import,
        )
    )
    lines.extend(
        build_runtime_only_test_repair_lines(
            summary_lower,
            failed_content_lower,
            surface_analysis.imported_module_symbols,
            surface_analysis.unknown_module_symbols,
            surface_analysis.previous_member_calls,
            surface_analysis.previous_constructor_keywords,
            required_evidence_runtime_issue,
            required_evidence_items,
        )
    )
    return lines


__all__ = ["build_test_validation_repair_lines"]