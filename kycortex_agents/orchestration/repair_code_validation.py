from typing import Optional

from kycortex_agents.orchestration.repair_analysis import render_name_list, suggest_declared_attribute_replacement


def build_code_validation_repair_lines(
    summary_lower: str,
    failed_content_lower: str,
    dataclass_order_examples: list[str],
    duplicate_constructor_argument_details: Optional[tuple[str, str]],
    duplicate_constructor_call_hint: Optional[str],
    duplicate_constructor_explicit_rewrite_hint: Optional[str],
    missing_attribute_details: Optional[tuple[str, str, list[str]]],
    nested_payload_wrapper_details: Optional[tuple[str, list[str], Optional[str]]],
    constructor_strictness_details: Optional[tuple[str, list[str], list[str]]],
    plain_class_field_details: Optional[tuple[str, str]],
    missing_import_details: Optional[tuple[str, Optional[str]]],
) -> list[str]:
    lines: list[str] = []

    if "task public contract: fail" in summary_lower:
        lines.append(
            "Treat the task public contract anchor as exact. Restore the named public facade, request model, and required workflow or validation methods before making secondary refactors."
        )
        lines.append(
            "Do not rename the public facade, request model, or required workflow surface to guessed aliases. Match the anchor-defined surface first, then repair behavior under that same surface."
        )
    if "pytest failure details:" in summary_lower:
        lines.append(
            "Treat the listed pytest failures as exact behavior requirements for the implementation. Fix the module so each cited assertion passes without changing the valid test surface."
        )
    if "assertionerror" in summary_lower or " - assert " in summary_lower:
        lines.append(
            "When the summary shows an exact boolean, numeric, or returned-value mismatch, change the implementation until that exact expectation holds; do not stop at a nearby constant tweak if the same assertion would still fail."
        )
    if "pytest execution: fail" in summary_lower or "pytest failed:" in summary_lower:
        lines.append(
            "Preserve the documented public API and repair the module behavior itself instead of renaming helpers, reshaping return values, or shifting the failure onto the tests."
        )
        lines.append(
            "Repair the implementation module itself. Return only importable module code, not pytest test functions, copied test bodies, or bare assertion snippets from the tests context."
        )
        lines.append(
            "If the task requires a CLI or demo entrypoint, preserve or restore a minimal main() plus a literal if __name__ == \"__main__\": block while fixing the cited behavior. Do not drop the entrypoint just to save lines."
        )
    if duplicate_constructor_argument_details is not None:
        class_name, field_name = duplicate_constructor_argument_details
        lines.append(
            f"If pytest reports TypeError from {class_name}.__init__() saying it got multiple values for argument '{field_name}', do not pass {field_name} both positionally and through **request.details, **request.data, **payload, or a duplicated keyword."
        )
        lines.append(
            f"When {field_name} is extracted separately before constructing {class_name}(...), remove it from any expanded mapping or switch to explicit keyword construction so each constructor field is bound exactly once."
        )
        if duplicate_constructor_call_hint:
            lines.append(
                f"The exact broken call {duplicate_constructor_call_hint} still appears in the failed artifact. Do not return that call unchanged; rewrite that construction so {field_name} is bound once and that exact call disappears from the final module."
            )
        if duplicate_constructor_call_hint and duplicate_constructor_explicit_rewrite_hint:
            lines.append(
                f"For this failed artifact, rewrite {duplicate_constructor_call_hint} to {duplicate_constructor_explicit_rewrite_hint} or an equivalent explicit constructor call that binds each field once and supplies safe defaults for fields omitted by valid inputs."
            )
    if missing_attribute_details is not None:
        class_name, attribute_name, class_fields = missing_attribute_details
        replacement_field = suggest_declared_attribute_replacement(attribute_name, class_fields)
        lines.append(
            f"If pytest reports AttributeError that '{class_name}' has no attribute '{attribute_name}', align the model fields and member accesses so every referenced attribute is actually declared or derived on that object."
        )
        if class_fields:
            lines.append(
                f"{class_name} currently defines {render_name_list(class_fields)}. If you keep .{attribute_name} in the rewritten module, add {attribute_name} to {class_name} and populate or derive it where {class_name} objects are created. Otherwise replace that access with one of the declared fields and remove every remaining read of .{attribute_name}."
            )
            if replacement_field:
                lines.append(
                    f"The closest declared field is {replacement_field}. Prefer replacing .{attribute_name} with .{replacement_field} rather than preserving an undeclared near-match attribute."
                )
        else:
            lines.append(
                f"If you keep .{attribute_name} in the rewritten module, declare it on {class_name} and populate or derive it where {class_name} objects are created. Otherwise remove every read of .{attribute_name} and use an existing declared field instead."
            )
    if nested_payload_wrapper_details is not None:
        container_name, offending_fields, validation_line = nested_payload_wrapper_details
        rendered_fields = render_name_list(offending_fields)
        lines.append(
            f"The current failed artifact still treats {rendered_fields} as required keys inside request.{container_name}. Keep those wrapper fields on the request object and reserve request.{container_name} checks for actual payload keys only."
        )
        if validation_line:
            lines.append(
                f"Do not return the broken validation line `{validation_line}` unchanged. Replace it with wrapper-field checks on the request object plus only true payload-key validation inside request.{container_name}."
            )
    if constructor_strictness_details is not None:
        class_name, missing_fields, required_fields = constructor_strictness_details
        rendered_missing_fields = render_name_list(missing_fields)
        lines.append(
            f"If valid happy-path or batch pytest cases fail with TypeError from {class_name}.__init__(), the implementation is stricter than the documented contract. Align that internal model with validate_request(...) and the cited valid inputs instead of pushing new required payload keys onto the tests."
        )
        if required_fields:
            lines.append(
                f"The current validator only requires {render_name_list(required_fields)}, so do not make {class_name}(...) additionally require {rendered_missing_fields}. Derive those internal values or give them safe defaults when building the internal record."
            )
        else:
            lines.append(
                f"Do not make {class_name}(...) additionally require {rendered_missing_fields} when those fields are not part of the documented valid input contract. Derive them or give them safe defaults when building the internal record."
            )
    if "follows default argument" in summary_lower:
        lines.append(
            "If a dataclass or typed record model fails with a 'non-default argument ... follows default argument' error, reorder the fields so every required non-default field appears before any field with a default while preserving the documented constructor contract."
        )
        lines.append(
            "Inspect every dataclass declaration in the failed module, including audit, review, and result record types. This import error can come from a helper record class even when the anchored request model already matches the public contract."
        )
        lines.append(
            "Example: declare AuditLog(action, details, timestamp=field(default_factory=...)) rather than placing timestamp before the required details field."
        )
        lines.extend(dataclass_order_examples)
    if "name 'field' is not defined" in summary_lower:
        lines.append(
            "If a dataclass uses field(...) or default_factory anywhere in the module, import field explicitly from dataclasses. Do not leave field referenced without that import."
        )
    if missing_import_details is not None:
        missing_name, broken_line = missing_import_details
        if missing_name == "dataclass":
            lines.append(
                "If the module uses @dataclass anywhere, import dataclass explicitly with `from dataclasses import dataclass` before the first decorator. Do not leave @dataclass in the final module without that import."
            )
        if broken_line and f"{missing_name}." in broken_line:
            lines.append(
                f"The module import is failing because `{broken_line}` uses {missing_name} before it is imported. If you keep that module-qualified reference, add `import {missing_name}` before first use instead of returning the same line unchanged."
            )
        elif broken_line:
            lines.append(
                f"The module import is failing because `{broken_line}` references {missing_name} before it is imported. Import the symbol that defines {missing_name} or rewrite that line to use an already imported name."
            )
        else:
            lines.append(
                f"The module import is failing because {missing_name} is referenced before it is imported. Add the missing import or rewrite every use of {missing_name} to match an actually imported symbol."
            )
    if plain_class_field_details is not None:
        class_name, field_name = plain_class_field_details
        lines.append(
            f"The current failed artifact defines {class_name}.{field_name} with field(...) on a non-dataclass class. That leaves {field_name} as a dataclasses.Field placeholder at runtime instead of a mutable instance value."
        )
        lines.append(
            f"For plain service classes, initialize self.{field_name} inside __init__ and keep zero-argument construction compatible with the documented facade. Only convert {class_name} to @dataclass if the same public methods and constructor behavior remain valid."
        )
    if (
        "name 'datetime' is not defined" in summary_lower
        or "name 'date' is not defined" in summary_lower
        or "name 'timedelta' is not defined" in summary_lower
        or "name 'timezone' is not defined" in summary_lower
        or (
            "nameerror" in summary_lower
            and any(
                token in failed_content_lower
                for token in ("datetime.", "timedelta(", "timezone.")
            )
        )
    ):
        lines.append(
            "Keep imports consistent with referenced names. If the module calls datetime.datetime.now(), datetime.date.today(), datetime.timedelta(...), or datetime.timezone.utc, import datetime; if it imports symbols directly with `from datetime import datetime, timedelta, timezone`, call datetime.now(), timedelta(...), or timezone.utc instead of datetime.datetime.now(), bare missing helpers, or mismatched module-qualified references. Do not leave module-qualified or bare references pointing at names that were never imported."
        )
    if "assert not true" in summary_lower or "assert true is false" in summary_lower:
        lines.append(
            "If pytest reports `assert not True` or `assert True is False` for validate_request or another validator, repair the implementation so that the cited invalid sample is actually rejected. Do not leave the validator as a presence-only required-key check when the failing sample already uses a clearly wrong required-field value or type."
        )
        lines.append(
            "Implement concrete reject conditions for clearly invalid required-field values or types instead of only checking whether every required key is present."
        )
    if (
        "valueerror" in summary_lower
        and "invalid" in summary_lower
        and any(token in summary_lower for token in ("test_happy_path", "test_batch", "test_batch_processing"))
        and "required_fields" in failed_content_lower
        and any(token in failed_content_lower for token in ("request.details", "request.data", "request.metadata", "request.payload"))
    ):
        lines.append(
            "If happy-path or batch pytest cases now raise `ValueError(...)` after a validator repair, inspect whether the validator started checking wrapper fields on the nested payload container. Keep top-level request fields such as request_id and request_type on the request object, and reserve request.details, request.data, request.metadata, or request.payload checks for actual payload keys only."
        )
        lines.append(
            "Do not require wrapper fields such as request_id, request_type, details, data, metadata, or payload as keys inside request.details, request.data, request.metadata, or request.payload unless the contract explicitly duplicates them there."
        )
    if "likely truncated" in summary_lower:
        lines.append(
            "If completion diagnostics say the module output was likely truncated, rewrite the full module from the top instead of patching a partial tail or appending a continuation."
        )
        lines.append(
            "Restore a complete importable module first, then trim optional helpers, comments, blank lines, and other non-essential scaffolding so the repaired file stays comfortably under the size budget with visible headroom."
        )
    if "typeerror" in summary_lower:
        lines.append(
            "Keep data-model semantics consistent: if the module defines dataclasses or typed request objects, validate and read them via attributes instead of mapping membership or subscripting unless the public contract explicitly uses dict inputs."
        )
    if "offset-naive and offset-aware datetimes" in summary_lower:
        lines.append(
            "Normalize every datetime comparison to one timezone convention before comparing timestamps. Do not mix parsed timezone-aware datetimes with naive datetime.now() values in certification, incident, cache, scoring, or audit paths."
        )
        lines.append(
            "If the cited tests construct naive datetimes with datetime(...), keep compared implementation timestamps naive too or convert both sides consistently before comparison. Every compared datetime in the same branch must share the same timezone awareness."
        )
    if "line count:" in summary_lower:
        lines.append(
            "Rewrite the full module smaller and leave clear headroom below the reported line ceiling. Remove optional helper layers, repeated convenience wrappers, and non-essential docstrings before touching required behavior."
        )

    return lines


__all__ = ["build_code_validation_repair_lines"]