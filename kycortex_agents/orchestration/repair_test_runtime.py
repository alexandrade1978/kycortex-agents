def _formatted_member_calls(previous_member_calls: dict[str, list[str]]) -> str:
    return "; ".join(
        f"{class_name}.{', '.join(member_names)}"
        for class_name, member_names in previous_member_calls.items()
    )


def _formatted_constructor_keywords(previous_constructor_keywords: dict[str, list[str]]) -> str:
    return "; ".join(
        f"{class_name}({', '.join(keyword_names)})"
        for class_name, keyword_names in previous_constructor_keywords.items()
    )


def build_runtime_only_test_repair_lines(
    summary_lower: str,
    failed_content_lower: str,
    imported_module_symbols: list[str],
    unknown_module_symbols: list[str],
    previous_member_calls: dict[str, list[str]],
    previous_constructor_keywords: dict[str, list[str]],
    required_evidence_runtime_issue: bool,
    required_evidence_items: list[str],
) -> list[str]:
    lines: list[str] = []

    if "pytest execution: fail" in summary_lower or "pytest failed:" in summary_lower:
        lines.append(
            "If the previous suite already passed static validation, preserve its valid imports, constructor shapes, fixture payload structure, and scenario skeleton unless the validation summary explicitly says one of those pieces is wrong."
        )
        if imported_module_symbols and not unknown_module_symbols:
            lines.append(
                "The previous suite already used a statically valid production import surface: "
                f"{', '.join(imported_module_symbols)}. Preserve that exact production symbol set during repair unless the validation summary explicitly marks one of those imports invalid."
            )
            lines.append(
                "Do not swap a previously valid documented symbol for a guessed alias or renamed service class. If the valid suite imported ComplianceIntakeService, do not replace it with ComplianceService or another invented variant just because pytest failed elsewhere."
            )
        if previous_member_calls:
            lines.append(
                "The previous statically valid suite already exercised these production member calls: "
                f"{_formatted_member_calls(previous_member_calls)}. Preserve those exact member names during repair unless the validation summary explicitly marks one of them invalid."
            )
            lines.append(
                "Do not replace a previously valid member call with a guessed workflow alias such as process_request or process_batch when the valid suite already used a different documented member name."
            )
        if "constructor arity mismatches: none" in summary_lower:
            lines.append(
                "When the previous suite had no constructor arity mismatches, keep the same request and result constructor field names and arity during repair unless the validation summary explicitly reports a constructor problem. Do not rewrite a statically valid request model to a different field set just because pytest failed on behavior."
            )
        if previous_constructor_keywords:
            lines.append(
                "The previous statically valid suite already instantiated production models with these keyword fields: "
                f"{_formatted_constructor_keywords(previous_constructor_keywords)}. Preserve those field names during repair unless the validation summary explicitly reports a constructor mismatch."
            )
            lines.append(
                "Do not rewrite a previously valid request model from fields such as request_id, request_type, details to guessed placeholders such as id, data, timestamp, or status unless the contract and validation summary explicitly require that change."
            )
        lines.append(
            "When repairing a suite that was already statically valid, preserve the exact documented public method names from the current suite and API contract. Do not rename submit_intake(...) to submit(...) or batch_submit_intakes(...) to submit_batch(...), even when calling the service inline."
        )
        lines.append(
            "If a pytest-only runtime failure comes from an overreaching assertion rather than a documented contract guarantee, rewrite that assertion to a contract-backed invariant instead of forcing a guessed business rule into the implementation."
        )
        if "assertionerror: assert" in summary_lower and " == " in summary_lower:
            lines.append(
                "When pytest reports an exact numeric mismatch such as `assert 0.4 == 0.1`, do not preserve the stale guessed literal from the earlier suite. Either recompute the expected value from the current implementation formula and the exact input used in that test, or replace the equality with a stable contract-backed invariant such as non-negativity, type, or relative ordering."
            )
            if "score ==" in failed_content_lower:
                lines.append(
                    "If an exact score depends on string length or character count, do not keep word-like sample strings such as data, valid_data, or data1 together with exact score equality. Replace them with repeated-character literals whose length is obvious, or switch the assertion to a non-exact invariant."
                )
                if any(token in failed_content_lower for token in ("name", "email", "@")):
                    lines.append(
                        "Do not hand-count human-readable names or email addresses into an exact score literal. If the formula uses lengths such as (len(name) + len(email)) / 10.0, compute the expected value from the current formula and the exact strings used, or switch to repeated-character inputs whose lengths are obvious."
                    )
            if any(token in failed_content_lower for token in ("risk_factor", "compliance_history")):
                lines.append(
                    "If a score formula combines weighted numeric fields, recompute the exact total from every exercised term using the current input values before asserting equality. Example: if score += request_data['risk_factor'] * 0.5 and score += (1 - request_data['compliance_history']) * 0.5, then risk_factor=2 and compliance_history=0.1 yield 1.45, not 1.25."
                )
            if "process_batch" in failed_content_lower and "score ==" in failed_content_lower:
                lines.append(
                    "Recompute each batch item's expected score independently from the same current formula applied to that item's actual input. Do not assume a later batch item should have a larger exact score just because nested values differ; if the formula counts top-level keys or container size, same-shape inputs produce the same score."
                )
        if "valueerror" in summary_lower and "must be filled" in summary_lower:
            lines.append(
                "If a non-error scoring or happy-path test fails because a required string field is empty, do not preserve that empty string just to force a zero score. Use a valid non-empty input that still yields the intended observable result, or replace the exact equality with a stable invariant."
            )
            if any(token in failed_content_lower for token in ("score_request", "score_risk")) and "intake_request" in failed_content_lower:
                lines.append(
                    "If invalid required fields are rejected during intake or validation, do not keep a separate invalid-scoring test that first calls intake_request and then expects score_request or score_risk to fail on the same invalid object. Move that failure case to intake_request or validate_request, and keep scoring tests on already-valid requests."
                )
            if any(token in failed_content_lower for token in ('""', "''")):
                lines.append(
                    "If a required string field participates in a length- or modulo-based score, an empty string is invalid once the implementation validates that field before scoring. Use a non-empty repeated-character literal with the needed length instead; for len(details) % 10 == 0, use \"xxxxxxxxxx\" rather than \"\"."
                )
        if "documents" in failed_content_lower and "risk_scores" in failed_content_lower:
            lines.append(
                "When the implementation validates a required document or evidence list before scoring, every happy-path or valid batch item must include the full required set named by that validator. Do not keep a single placeholder document such as ['ID'] if the implementation names additional required evidence items."
            )
            lines.append(
                "If the implementation shows a named required_evidence or required_documents list, copy that full list verbatim into every valid happy-path or valid batch payload instead of shrinking it to a representative subset."
            )
            lines.append(
                "Keep the missing-document scenario isolated to the explicit validation-failure test, and make every supposedly valid happy-path or batch item fully valid before asserting scored outcomes or approved audit entries."
            )
            if "test_validation_failure" in failed_content_lower or '"documents": []' in failed_content_lower or "'documents': []" in failed_content_lower:
                lines.append(
                    "When the suite already contains a dedicated validation-failure case, do not reuse that invalid missing-document payload inside test_batch_processing or any other supposedly valid batch scenario. Keep every batch item fully valid unless the contract explicitly documents partial batch failure handling."
                )
        if required_evidence_runtime_issue:
            lines.append(
                "Do not copy the current failed suite forward unchanged. The supposed happy-path or batch payloads still omit required evidence named by the implementation validator, so rebuild those valid request payloads from the current validator contract before returning the rewritten file."
            )
            if required_evidence_items:
                lines.append(
                    f"The implementation names the full required evidence list as {required_evidence_items!r}. Copy that exact list into every valid happy-path or valid batch payload, and keep missing-document coverage isolated to the explicit validation-failure test."
                )
            lines.append(
                "If test_batch_processing asserts the full batch size on len(service.risk_scores) or another success-path count, every batch item in that scenario must be fully valid. Do not keep a second batch request with reduced or empty documents such as ['ID'] or [] unless the contract explicitly documents partial batch failure handling."
            )
        if "risk_scores" in failed_content_lower and ".score > 0" in failed_content_lower:
            lines.append(
                "Do not require a strictly positive score or non-empty risk list from a generic happy-path input unless the chosen payload actually exercises a documented risk factor. For a plain valid request, prefer asserting that scoring completed, a risk record exists, or the score is non-negative."
            )
        if ".data ==" in failed_content_lower:
            lines.append(
                "If a returned request object's `.data` field stores the full input payload, do not assert that it equals only a guessed inner sub-dict. Assert the full stored payload shape or direct nested keys instead."
            )
            if "score ==" in failed_content_lower or "data_field" in failed_content_lower:
                lines.append(
                    "If an exact score depends on nested payload shape, compute it from the actual object passed into the scoring function rather than from an inner dict you assume the service extracted. If request.data stores {'id': '1', 'data': {'data_field': 'example'}, 'timestamp': '...'} and calculate_risk_score reads data.get('data_field', ''), the score is 0.0, not 7.0."
                )
        lines.append(
            "Do not assume empty strings, placeholder IDs, or domain keywords are invalid unless the contract or implementation explicitly says so. For validation-failure coverage, prefer missing required fields or clearly wrong types over guessed business rules."
        )
        lines.append(
            "If the implementation only checks types such as isinstance(id, str) or isinstance(data, dict), do not use empty strings or same-type placeholders as the failing input because they still satisfy that validator. Switch the failure case to a clearly wrong type or a truly missing required field instead."
        )
        if "audit" in summary_lower or "log" in summary_lower:
            lines.append(
                "If the remaining pytest failure comes from a standalone audit or logging helper test in a compact helper-only suite, delete that standalone helper test or fold the audit call into a required happy-path or batch scenario instead."
            )
            lines.append(
                "Do not compare full audit or log file contents by exact string equality or trailing-newline-sensitive text unless the contract explicitly defines that serialized format. Prefer stable assertions such as file creation, non-empty content, append growth, line count, or required substring presence."
            )
            if "audit_logs" in failed_content_lower or "len(service.audit_logs)" in failed_content_lower:
                lines.append(
                    "If pytest shows a mismatch such as `assert 5 == 3` or `assert 2 == 3` on len(service.audit_logs) in a batch scenario, the suite guessed internal logging. Delete that exact len(service.audit_logs) == N assertion unless the contract explicitly enumerates every emitted batch log."
                )
                lines.append(
                    "Replace brittle batch audit counts with stable checks such as result length, required audit actions, a terminal batch marker, or monotonic audit growth."
                )
                lines.append(
                    "If an audit-count assertion failed, recount only the audit actions that the scenario actually executes. Add logs from both inner failing operations and outer batch error handlers instead of assuming one failure contributes only one audit record. When the test performs intake, scoring, and one error path, the expected audit count is three entries, not two."
                )
                lines.append(
                    "If you cannot enumerate every emitted audit event from the current implementation, stop asserting an exact batch audit length and switch to stable checks such as required actions, terminal batch markers, result counts, or monotonic audit growth."
                )
                if "process_batch" in failed_content_lower:
                    lines.append(
                        "In a mixed valid/invalid batch scenario, one invalid item can emit two failure-related audit records, such as an intake or validation failure log plus a batch-level failure log. Add those to any success-path logs from valid items before asserting an exact audit total."
                    )
                    lines.append(
                        "If process_batch internally performs more than one logged success step per valid item, count each of those inner success-path logs before any batch-level or failure logs. Example: a two-item valid batch can emit 5 audit logs, not 3, and a batch that fails on the second item can still already emit 2 logs, not 1, from the first valid item."
                    )
        if "exact batch audit length" in summary_lower:
            lines.append(
                "The previous suite overreached by asserting a batch audit length larger than the visible number of processed items. Delete that guessed extra-count assertion and rebuild the batch scenario around result count, request identity, or monotonic audit growth unless the contract explicitly defines extra summary entries."
            )
        if "exact status/action label mismatch" in summary_lower:
            lines.append(
                "The previous runtime failure came from a brittle exact status or action label guess. Unless the contract explicitly defines the trigger, replace blocked, escalated, or approved label guesses with stable invariants or with clearly non-borderline inputs whose outcome is documented."
            )
            lines.append(
                "If you keep an exact status or action assertion, anchor it to a validation-failure path or another trigger that the implementation summary or behavior contract defines directly."
            )
            lines.append(
                "For happy-path or valid batch scenarios, do not assert exact outcome strings such as straight-through, manual review, manual investigation, fraud, fraud escalation, or time-boxed approval unless the contract explicitly defines that input-to-label mapping. Prefer request identity, audit growth, or another documented invariant instead."
            )
            lines.append(
                "Apply the same rule to return-review labels such as auto-approve, manual inspection, and abuse escalation. Do not hard-code those happy-path or batch outcomes unless the contract explicitly defines that mapping."
            )
        if "exact internal action-map key assumption" in summary_lower:
            lines.append(
                "The previous runtime failure came from assuming an internal action or review map used request identity as its key. Do not assert request.request_id in service.review_actions or a similar membership check unless the contract explicitly defines that storage key."
            )
            lines.append(
                "If the implementation stores ReviewAction(action_id, ...) or another action record with its own generated identifier, assert the collection size, inspect stored action values, or check a documented action_type instead of assuming the map key equals request_id, vendor_id, or another request-identity field."
            )
        if "exact validation-failure score-state emptiness assertion" in summary_lower:
            lines.append(
                "The previous runtime failure came from assuming a rejected or invalid request leaves internal score state empty. Do not assert len(service.get_risk_scores()) == 0 or a similar exact zero-length check on internal score maps, caches, or derived-state collections unless the behavior contract explicitly guarantees that post-validation state."
            )
            lines.append(
                "For validation-failure coverage, prefer the rejected return value, documented audit or action evidence, or another observable contract-backed effect over a guessed exact internal score-state size."
            )
            lines.append(
                "In a validation-failure test, remove direct reads of service.get_risk_scores() or similar internal score state unless that post-failure state is itself the documented contract. Assert the rejected return value, blocked audit entry, or another documented effect instead."
            )
        if "exact return-shape attribute assumption" in summary_lower:
            lines.append(
                "The previous runtime failure came from assuming a wrapped object return shape that the current runtime did not provide. Delete `.request_id`, `.outcome`, and similar attribute reads on the workflow return value unless the contract explicitly exposes that wrapper type."
            )
            lines.append(
                "If the workflow currently returns a direct string or other primitive, keep happy-path and batch assertions on that direct value or on documented side effects instead of inventing a wrapper object."
            )
        if all(name in summary_lower for name in ("validate_request", "score_request", "log_audit")):
            lines.append(
                "For a helper-only trio such as validate_request(request), score_request(request), and log_audit(request_id, action, result), collapse the suite to exactly three tests: one happy-path test that validates and scores a valid request and may check audit file creation or required substring presence, one validation-failure test using an invalid document_type or wrong-type document_data, and one batch-style loop over two valid requests. Delete standalone score_request, log_audit, and extra invalid-case tests."
            )
            lines.append(
                "When a helper-only trio has branch-specific score increments, derive the exact expected score from only the branches exercised by the chosen input. Do not add values from categories the input does not trigger."
            )
            lines.append(
                "Example: if score_request adds 1 for document_type == 'income' and 2 for document_type == 'employment', a request with document_type='income' should assert 1, not 3."
            )
        if "argparse" in summary_lower or "dataclass" in summary_lower:
            lines.append(
                "Delete any copied implementation blocks from the pytest module. Do not redeclare dataclasses, business functions, CLI parsers, `test_main`, `test_all_tests`, or similar scaffolding inside tests; import production symbols and keep only focused test cases."
            )
        lines.append(
            "When behavior is uncertain, prefer stable invariants and type or shape assertions over guessed exact numeric values."
        )
        lines.append(
            "If the implementation summary or behavior contract does not explicitly define a score formula or threshold flag trigger, remove exact score totals and threshold-triggered boolean assertions and replace them with stable invariants or relative comparisons."
        )
    if "did not raise" in summary_lower:
        lines.append(
            "When a failure case did not raise, rebuild that scenario around an input that actually violates the current validator or contract. If validation only checks isinstance(id, str) and isinstance(data, dict), do not use empty-string ids or still-valid dict payloads as the failure input."
        )
        lines.append(
            "If a workflow input still has the correct top-level type, do not expect ValueError just because one business value changed. Example: if submit_intake only validates that data.data is a dict, ComplianceData(id=\"1\", data={\"key\": \"wrong_value\"}) is still valid input and should be asserted as a non-compliant result instead of being wrapped in pytest.raises(ValueError). Use a non-dict payload if you need a ValueError case."
        )
        lines.append(
            "If the field under test is a dict payload such as data, details, metadata, request_data, or document_data, an empty dict is still a same-type placeholder and may pass when validation only checks dict type. Use None, a non-dict value, or omit the field only when omission is explicitly allowed."
        )
        lines.append(
            "If validation only checks an outer container type, do not assume a wrong nested value type makes the request invalid. When validate_request(request) returns bool(request.id) and isinstance(request.data, dict), ComplianceRequest(id=\"1\", data={\"check\": \"not_a_bool\"}, timestamp=\"2023-01-01T00:00:00Z\", status=\"pending\") still passes; use a non-dict data value or another explicitly invalid top-level field instead."
        )
        lines.append(
            "For process_request or other validation-gated workflow tests, choose an input that validate_request rejects before scoring runs. Do not use nested None values or same-type empty containers that can slip past validation and then fail later inside score_risk, calculate_risk_score, or similar scoring helpers with a different exception."
        )
        if "exact return-shape attribute assumption" in summary_lower:
            lines.append(
                "If the same failed suite also overreached on return shape, rebuild happy-path and batch checks around the direct primitive returned by the workflow, and reserve pytest.raises only for an input that the current validator demonstrably rejects."
            )
        if any(token in failed_content_lower for token in ("risk_factor", "compliance_history", "request_data")):
            lines.append(
                "Do not expect a wrong nested field type to raise just because that field participates in scoring. When the implementation guards a nested field with isinstance(...) before using it, a wrong nested field type is ignored rather than raising; use a wrong top-level type or missing required field for failure coverage instead."
            )
    if "assert false" in summary_lower or "assert true" in failed_content_lower or "assuming " in failed_content_lower:
        lines.append(
            "Do not leave placeholder assertions such as assert True, assert False, or comments like 'Assuming ...' in the rewritten suite. Replace them with a concrete contract-backed expectation."
        )
        lines.append(
            "For validation-failure coverage, prefer an explicit validation result, a documented raised exception, or another observable side effect over a placeholder boolean assertion."
        )
    if "assert not true" in summary_lower or "assert true is false" in summary_lower:
        lines.append(
            "If pytest reports `assert not True` or another failed falsy expectation from validate_request, process_request, or a similar validator, the supposed invalid sample likely still satisfies the current contract. Apply the same rule to `assert True is False`. Replace it with a clearly wrong top-level type or a truly missing required field instead of an empty-string or same-type placeholder."
        )
        lines.append(
            "Apply the same rule to request_id, entity_id, document_id, and similar identifiers: unless the contract explicitly says empty strings are invalid, do not use request_id='' or another same-type placeholder as the failing input."
        )
        lines.append(
            "If the field under test is a dict payload such as data, details, metadata, request_data, or document_data, do not use an empty dict or nested None values to fake a validation failure. Use a wrong top-level type or another input that validate_request actually rejects before scoring runs."
        )
        lines.append(
            "If the current validator only checks for the presence of required payload fields, do not keep every named key with same-type placeholder values like \"value\" in the rejection case. Omit one required field or use another clearly invalid top-level type instead."
        )
    if "assert false" in summary_lower:
        lines.append(
            "Do not require an exact runtime numeric type such as float unless the contract or implementation explicitly casts to that type. For numeric scores, prefer the documented value, non-negativity, or a broader numeric invariant such as isinstance(value, (int, float))."
        )
    if "assertionerror" in summary_lower or " - assert " in summary_lower:
        lines.append(
            "Do not infer derived statuses, labels, or report counters from suggestive field names or keywords alone. Keep exact categorical or counter assertions only when the contract or current implementation explicitly defines that trigger."
        )
        if any(label in summary_lower for label in ("low", "medium", "high")):
            lines.append(
                "Do not keep boundary-like inputs for exact categorical labels. If score = amount * 0.1 and the label may change at 10, do not use amount=100 to assert an exact level; use 50 for a clear low case, 150 for a clear medium case, or assert only the numeric score unless the thresholds are explicit."
            )
            lines.append(
                "If the score is count-based and the thresholds are not explicit, do not use a borderline count such as 2 to assert an exact low label; use 1 for a clear low case, 3 for a clear medium case, or assert only the numeric score."
            )

    return lines


__all__ = ["build_runtime_only_test_repair_lines"]