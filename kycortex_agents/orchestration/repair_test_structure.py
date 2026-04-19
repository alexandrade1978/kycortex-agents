def build_structural_test_repair_lines(
    summary_lower: str,
    failed_content_lower: str,
    imported_module_symbols: list[str],
    undefined_available_module_symbols: list[str],
    helper_alias_names: list[str],
    unknown_module_symbols: list[str],
    helper_surface_symbols: list[str],
    assertionless_tests: list[str],
    missing_datetime_import_issue: bool,
    implementation_prefers_direct_datetime_import: bool,
) -> list[str]:
    lines: list[str] = []

    lines.append(
        "Rewrite the full pytest module from the top, but treat the current implementation artifact and API contract as fixed ground truth. Remove any test, fixture, or helper that is not required by the documented scenarios."
    )
    lines.append(
        "Do not invent replacement classes, functions, validators, return-wrapper types, helper names, or alternate constructor signatures during repair."
    )
    if helper_surface_symbols:
        rendered_symbols = ", ".join(helper_surface_symbols)
        lines.append(
            "Delete every import, fixture, helper variable, and top-level test that references these flagged helper surfaces: "
            f"{rendered_symbols}. Do not repair those helper-surface tests in place."
        )
        lines.append(
            "Replace that coverage with the documented higher-level workflow or service surface from the test targets, and do not reintroduce "
            f"{rendered_symbols} anywhere in the rewritten file unless the public API contract explicitly makes one of them the primary surface under test."
        )
        lines.append(
            "When the module exposes a higher-level service or workflow facade, keep imports limited to that facade and directly exchanged domain models instead of auxiliary validators, scorers, loggers, repositories, processors, or engines."
        )
        lines.append(
            "Do not replace one guessed helper with another guessed helper during repair. If a helper-surface test was invalid for a name such as ComplianceScorer, ComplianceBatchProcessor, or AuditLogger, delete that helper-oriented test and rebuild around the documented service facade and request or result models only."
        )
    elif "helper surface usages:" in summary_lower:
        lines.append(
            "Delete every import, fixture, helper variable, and top-level test that references the flagged helper surfaces from the validation summary. Do not repair those helper-surface tests in place."
        )
        lines.append(
            "Replace removed helper-surface coverage with the documented higher-level workflow or service surface from the test targets, and do not reintroduce the flagged helper names anywhere in the rewritten file."
        )
        lines.append(
            "When the module exposes a higher-level service or workflow facade, keep imports limited to that facade and directly exchanged domain models instead of auxiliary validators, scorers, loggers, repositories, processors, or engines."
        )
        lines.append(
            "Do not replace one guessed helper with another guessed helper during repair. If a helper-surface test was invalid for a name such as ComplianceScorer, ComplianceBatchProcessor, or AuditLogger, delete that helper-oriented test and rebuild around the documented service facade and request or result models only."
        )
    if any(marker in summary_lower for marker in ("line count:", "top-level test functions:", "fixture count:")):
        lines.append(
            "Reduce scope aggressively: target 3 to 4 top-level tests and no more than 2 fixtures unless the contract explicitly requires more. Count top-level tests and total lines before finalizing, and if you are still over budget, delete helper-only coverage first."
        )
        lines.append(
            "Target clear headroom below the line ceiling instead of landing on the boundary. Strip docstrings, comments, blank lines, and optional helper scaffolding before deleting any required scenario."
        )
        lines.append(
            "Keep only the minimum required scenarios: one happy path, one validation failure, and one batch or audit/integration path unless the contract explicitly requires more. Drop validator, scorer, serialization, logger, and other helper-level tests before cutting any required scenario."
        )
        lines.append(
            "When a compact suite is already over the top-level cap, delete standalone validator, scorer, and audit helper tests before keeping any extra coverage."
        )
    if "top-level test functions:" in summary_lower:
        lines.append(
            "If the validation summary reports too many top-level tests, delete or merge the lowest-value extra scenarios until the rewritten file is back under the stated maximum before addressing optional cleanup. A suite over the hard cap is invalid even when pytest passes."
        )
    if "tests without assertion-like checks:" in summary_lower and "tests without assertion-like checks: none" not in summary_lower:
        lines.append(
            "Every top-level test must contain at least one explicit assertion-like check such as assert ..., with pytest.raises(...), or another direct contract-backed expectation. Rewrite any hollow smoke test that only calls production code without verifying the outcome."
        )
        if assertionless_tests:
            lines.append(
                "The validation summary already flagged these hollow top-level tests: "
                f"{', '.join(assertionless_tests)}. Rewrite each named test so it contains at least one direct contract-backed expectation, or delete the test if you cannot assert a stable observable outcome without guessing internals."
            )
            lines.append(
                "Do not keep a call-only happy-path or batch test. For every named hollow test, assert returned values, raised exceptions, mutated state, audit record growth, or another externally observable outcome instead of only calling production code."
            )
            if len(assertionless_tests) > 1:
                lines.append(
                    "When more than one top-level test is hollow, discard the current pytest skeleton and rewrite the entire suite from scratch around only the minimum required scenarios instead of patching the previous file in place. Preserve only the valid import surface and constructor shapes from the old suite."
                )
    if any(marker in summary_lower for marker in ("unknown module symbols:", "missing function imports:", "undefined local names:")):
        lines.append(
            "Use only documented module symbols and explicitly import every production class or function you reference in tests or fixtures."
        )
        lines.append(
            "Do not derive new helper names by adding or removing prefixes or suffixes from documented symbols. If the contract lists BatchProcessor or RiskScorer, do not invent ComplianceBatchProcessor, ComplianceScorer, ComplianceIntake, AuditLogger, or similar aliases."
        )
        lines.append(
            "If you use isinstance or another exact type assertion against a production class, import that class explicitly; otherwise rewrite the assertion to check returned fields or behavior without naming an unimported type."
        )
        if "request.timestamp" in failed_content_lower or "timestamp=request." in failed_content_lower:
            lines.append(
                "Do not satisfy explicit constructor fields by reading attributes from the object you are still constructing or any other undefined local. Define a self-contained value first and pass it directly, for example timestamp=fixed_time instead of timestamp=request.timestamp."
            )
        if undefined_available_module_symbols:
            lines.append(
                "The previous file referenced real module symbols without importing them: "
                f"{', '.join(undefined_available_module_symbols)}. Add those names to the import list from the target module before use instead of deleting, renaming, or leaving them as undefined locals."
            )
        if helper_alias_names:
            rendered_names = ", ".join(helper_alias_names)
            lines.append(
                "The previous file referenced undefined helper or collaborator aliases outside the documented import surface: "
                f"{rendered_names}. Delete that guessed helper wiring instead of preserving or patching those aliases in place."
            )
            near_match_pairs: list[str] = []
            for helper_name in helper_alias_names:
                normalized_helper = helper_name.lower()
                for symbol in imported_module_symbols:
                    normalized_symbol = symbol.lower()
                    if normalized_symbol == normalized_helper:
                        continue
                    if normalized_symbol in normalized_helper or normalized_helper in normalized_symbol:
                        pair = f"{helper_name} -> {symbol}"
                        if pair not in near_match_pairs:
                            near_match_pairs.append(pair)
            if near_match_pairs:
                lines.append(
                    "Do not repair those names by swapping to a near-match imported symbol with a different role or constructor contract, such as "
                    f"{', '.join(near_match_pairs)}."
                )
            lines.append(
                "Record or value classes such as audit logs, score records, and result objects are not service collaborators unless the contract explicitly says so. Assert on the outputs they produce instead of constructing them as service wiring."
            )
    if "invalid member references:" in summary_lower and "invalid member references: none" not in summary_lower:
        lines.append(
            "When invalid member references are reported, rewrite every method or attribute access to the exact documented public API for that class. Do not call guessed aliases on inline service instances such as ComplianceIntakeService().submit(...) or .submit_batch(...); use only the listed names like submit_intake(...) and batch_submit_intakes(...)."
        )
        lines.append(
            "Do not assume constructor chaining authorizes new member names. If the validation summary names Class.member as invalid, delete or rename that member access exactly as reported until the invalid-member list is empty."
        )
    if "imported entrypoint symbols:" in summary_lower or "unsafe entrypoint calls:" in summary_lower:
        lines.append(
            "Delete imported entrypoint symbols such as main, cli_demo, or similar CLI/demo helpers from the pytest module. Do not import or execute entrypoints in tests; cover only documented service, batch, or domain-model behavior."
        )
    if "undefined local names: pytest" in summary_lower:
        lines.append(
            "If the rewritten suite uses the `pytest.` namespace anywhere, add `import pytest` explicitly at the top of the file. Do not leave `pytest.raises`, `pytest.mark`, or similar helpers unimported."
        )
    if "undefined local names: datetime" in summary_lower or "name 'datetime' is not defined" in summary_lower:
        lines.append(
            "If the rewritten suite keeps any `datetime.now()` call or other bare `datetime` reference, add `from datetime import datetime` or `import datetime` explicitly at the top of the file before finalizing. Otherwise remove every bare datetime reference and use a self-contained timestamp value that still matches the implementation contract."
        )
        lines.append(
            "The current failed suite still contains bare `datetime` constructor arguments without a valid import. Before finalizing, either add the import or remove every bare `datetime.now()` reference; no unresolved bare `datetime` token should remain anywhere in the rewritten file."
        )
        if missing_datetime_import_issue:
            lines.append(
                "Do not copy the current failed suite forward unchanged. It already contains bare `datetime` references without a matching import, so rebuild the file from the documented contract and deterministic scaffold instead of preserving that invalid import surface."
            )
            if implementation_prefers_direct_datetime_import:
                lines.append(
                    "The current implementation already imports `from datetime import datetime`. Match that style in tests and prefer a local fixed timestamp such as `fixed_time = datetime(2024, 1, 1, 0, 0, 0)` for constructor arguments instead of repeating bare `datetime.now()` calls."
                )
    if "likely truncated" in summary_lower:
        lines.append(
            "If completion diagnostics say the previous pytest output was likely truncated, discard the partial tail and rewrite the complete pytest module from the top before reintroducing any optional assertions or fixtures."
        )
        lines.append(
            "Rebuild the minimum contract-backed suite first and leave visible headroom below the line, test-count, and fixture budgets before adding extra assertions."
        )
    if "constructor arity mismatches:" in summary_lower and "constructor arity mismatches: none" not in summary_lower:
        lines.append(
            "When constructor arity mismatches are reported, remove guessed helper wiring and rebuild the suite around the smallest documented public service or function surface using only listed constructor signatures."
        )
        lines.append(
            "Instantiate typed request or result models with the exact field names and full constructor arity listed in the API contract instead of inventing generic placeholders such as id, data, timestamp, or status. Pass every documented constructor field explicitly, including trailing defaulted fields, unless the contract explicitly shows omission as valid."
        )
        lines.append(
            "Do not rely on dataclass defaults just because omission would run. If the contract lists defaulted fields such as timestamp and status, pass them explicitly in every constructor call. Example: ComplianceRequest(id=\"1\", data={\"name\": \"John Doe\", \"amount\": 1000}, timestamp=1.0, status=\"pending\")."
        )
        lines.append(
            "When the mismatch report names multiple lines for the same constructor, rewrite every constructor call for that type in the file until the mismatch list is empty."
        )
    if "payload contract violations:" in summary_lower and "payload contract violations: none" not in summary_lower:
        lines.append(
            "When a called API expects a payload or filter dict with documented required fields, either provide every required field or omit that optional payload entirely. Do not keep partial dicts that the contract does not permit."
        )
    if "non-batch sequence calls:" in summary_lower:
        lines.append(
            "Keep scalar functions scalar: do not pass lists into single-request validators or scorers. Use the real batch API or iterate over valid single items."
        )
    if "reserved fixture names:" in summary_lower:
        lines.append("Never define a custom fixture named request.")
    if "unsupported mock assertions:" in summary_lower:
        lines.append(
            "Do not use mock-style assertion bookkeeping unless the same test installs the exact mock or patch target first."
        )

    return lines


__all__ = ["build_structural_test_repair_lines"]