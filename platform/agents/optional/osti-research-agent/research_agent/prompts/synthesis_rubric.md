Grade the assistant's final answer to the research question.

The copy of the findings in the transcript may be truncated. Call
`read_verified_findings` first and judge every claim against its output, not
against the transcript. `Paper N` refers to the finding whose `paper` is N.

Criteria:
1. Every factual sentence cites at least one `Paper N`, and every cited N is
   the number of an existing finding.
2. Every number, unit, and test condition in a sentence appears in the answer
   or evidence of a finding that sentence cites.
3. No claim comes from anywhere but the findings: no general knowledge and no
   unstated calculations.
4. Where findings disagree, the answer says so and gives the differing
   conditions or methods the findings report. If they do not disagree, this
   criterion passes.
5. The answer directly addresses the research question, and says plainly when
   the findings do not report a requested value instead of estimating one.
6. The answer states its limitations.
7. Every finding whose `match` is `nearest` is presented as data at the
   conditions it was reported at, not as the value at the asked conditions.


Return your verdict by calling the `GraderResponse` tool. If you cannot call
it, reply with only its JSON object and nothing else:
{"result": "satisfied" | "needs_revision" | "failed", "explanation": "...",
"criteria": [{"name": "...", "passed": true}, {"name": "...", "passed": false, "gap": "..."}]}
