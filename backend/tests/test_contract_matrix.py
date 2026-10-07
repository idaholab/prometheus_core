"""Contract-matrix verification (task 10) — no live stack required.

Three guarantees the frozen wire contract must hold, exercised as pure mappings:

1. **Status coverage.** Every ``ConversationStatus`` the client-agent can emit maps
   through ``chat_service.map_response`` to a valid ``ChatMessageResponse`` carrying a
   ``ChatStatus`` the frontend knows — no status falls through to a 500. This mirrors
   ``tests/infrastructure/test_contract_static.py`` ("handles every
   ``ConversationStatus.values()``") on the backend side of the wire.
2. **Render-hint classification.** ``to_artifact_meta`` assigns the right viewer
   ``render_hint`` for each artifact kind in ``docs/docs/dev-docs/artifacts.md``
   (pdf/data/report/file/ifc/exodus/stl/mermaid/reference/thermal/unknown).
3. **Follow-up normalization.** ``normalize_followup_questions`` collapses the loose,
   historically-varying agent question shapes handled in
   ``message_handler._handle_needs_info`` onto the frozen ``FormField`` schema.

The classifier/normalizer are also spot-checked in ``test_artifacts.py`` and
``test_chat_turn.py``; here they are asserted as an exhaustive *contract* matrix so a
new status or a dropped artifact kind fails loudly in one place.
"""

import pytest

from app.a2a_client import ConversationResponse, ConversationStatus
from app.contract import ChatStatus
from app.services import chat as chat_service
from app.services.artifacts import to_artifact_meta
from app.sessions import SessionStore

SID = "sid-1"


def _resp(**kwargs) -> ConversationResponse:
    return ConversationResponse.from_payload({"conversation_id": "c1", **kwargs})


async def _seed(store: SessionStore) -> None:
    """Bind the session to a conversation in Valkey.

    ``map_response`` reads and writes session state through the store now, so the
    mapping tests need a real (fake-Valkey-backed) session rather than a constructed
    ``SessionState`` — that type is a frozen snapshot.
    """
    await store.reset(SID, "c1")


# --------------------------------------------------------------------------- #
# 1. Status coverage — every ConversationStatus maps without a 500
# --------------------------------------------------------------------------- #


def test_status_vocabulary_matches_upstream():
    """Our public ``ChatStatus`` set must equal ``ConversationStatus.values()``.

    Same assertion as ``test_contract_static.py`` ("statuses handled by frontend
    exist in contract"), enforced here so adding an upstream status without adding a
    ``ChatStatus`` member (and a ``map_response`` branch) fails immediately.
    """
    assert {s.value for s in ChatStatus} == set(ConversationStatus.values())


# Minimal, representative payload per status. Deliberately sparse: map_response must
# not require optional fields to be present for any status.
_STATUS_PAYLOADS = {
    "needs_info": {"followup_questions": [{"field": "material", "question": "Which material?"}]},
    "plan_ready": {"plan": {"steps": [{"name": "step-1"}]}, "message": "Plan ready"},
    "executing": {"message": "Executing the plan…"},
    "completed": {
        "report": "Analysis complete.",
        "new_artifacts": [{"artifact_id": "a1", "name": "result.json", "mime_type": "application/json"}],
        "artifacts": [{"artifact_id": "a1", "name": "result.json"}],
    },
    "recommendation": {"response_text": "Use SS316.", "recommended_materials": ["SS316", "SS347"]},
    "answer": {"response_text": "The melting point is 1400C."},
    "backgrounded": {"message_metadata": {"task_id": "task-bg-1"}},
    "error": {"message": "Something failed."},
}


@pytest.mark.parametrize("source_status", ConversationStatus.values())
async def test_map_response_handles_every_status(source_status, session_store):
    """Each upstream status maps 1:1 to the same ``ChatStatus`` and round-trips.

    Guarantees the backend never lets a valid ``ConversationStatus`` fall through to
    the unknown-status fallback (which would silently relabel it ``answer``).
    """
    await _seed(session_store)
    response = _resp(status=source_status, **_STATUS_PAYLOADS[source_status])
    mapped = await chat_service.map_response(
        response, "turn-1", session_store, SID, conversation_id="c1", auto_approve=False
    )

    assert mapped.turn_id == "turn-1"
    # use_enum_values=True → status is the string value; must equal the source status.
    assert mapped.status == source_status
    assert mapped.status in set(ConversationStatus.values())
    # Must serialize cleanly (no non-JSON-able field leaked through the mapping).
    mapped.model_dump_json()


@pytest.mark.parametrize("source_status", ConversationStatus.values())
async def test_map_response_handles_bare_payload(source_status, session_store):
    """Even a status-only response (no optional fields) maps without raising."""
    await _seed(session_store)
    mapped = await chat_service.map_response(
        _resp(status=source_status), "t", session_store, SID, conversation_id="c1", auto_approve=False
    )
    assert mapped.status == source_status


def test_upstream_status_enum_rejects_unknown_values():
    """The first line of defense: ``ConversationResponse`` can't carry a bad status.

    ``from_payload`` validates ``status`` against ``ConversationStatus``, so an
    out-of-vocabulary value never reaches the backend as a parsed response. This
    parallels ``test_contract_static.py``'s "frontend rejects unknown status loudly".
    """
    with pytest.raises(Exception):
        _resp(status="some_future_status")


async def test_map_response_unknown_status_collapses_to_answer_not_500(session_store):
    """Belt-and-suspenders: the defensive ``else`` branch degrades, never 500s.

    The enum above makes this unreachable for a real parsed response, but
    ``map_response`` still guards it (mirroring the Chainlit ``else`` fallthrough) so a
    hand-built or future response object collapses to ``answer`` instead of crashing.
    A minimal stub stands in for the otherwise-unconstructable out-of-vocab response.
    """
    from types import SimpleNamespace

    await _seed(session_store)
    stub = SimpleNamespace(status="some_future_status", message="hi", response_text="body")
    mapped = await chat_service.map_response(stub, "t", session_store, SID, conversation_id="c1", auto_approve=False)
    assert mapped.status == ChatStatus.ANSWER.value
    assert mapped.response_text == "body"


# --------------------------------------------------------------------------- #
# 2. Render-hint classification across every artifact kind in artifacts.md
# --------------------------------------------------------------------------- #

# Keyed by the artifact "type" vocabulary in docs/docs/dev-docs/artifacts.md. The
# doc's classifier types collapse onto our RenderHint set: "data" → json (JSON/CSV
# share the JSONViewer) and markdown/plain "report" → report (rendered inline; A-1),
# while a report tagged onto a concrete PDF stays pdf. Each row is a realistic catalog
# dict as an agent emits it.
_ARTIFACT_MATRIX = [
    ("pdf", {"artifact_id": "p", "mime_type": "application/pdf"}, "pdf"),
    ("data-json", {"artifact_id": "d1", "mime_type": "application/json"}, "json"),
    ("table-csv-mime", {"artifact_id": "d2", "mime_type": "text/csv"}, "table"),  # A-9: CSV → table viewer
    ("table-tsv-ext", {"artifact_id": "d4", "name": "results.tsv"}, "table"),
    (
        "table-plaintext-csv-name",
        {"artifact_id": "d5", "mime_type": "text/plain", "name": "results.csv"},
        "table",
    ),
    ("data-tag", {"artifact_id": "d3", "tags": ["data"]}, "json"),
    ("report-pdf", {"artifact_id": "r1", "mime_type": "application/pdf", "tags": ["report"]}, "pdf"),
    ("report-markdown", {"artifact_id": "r2", "mime_type": "text/markdown"}, "report"),
    ("code-yaml-mime", {"artifact_id": "y1", "mime_type": "application/yaml"}, "code"),
    ("code-yaml-ext", {"artifact_id": "y2", "name": "config.yml"}, "code"),
    (
        "code-plaintext-yaml-name",
        {"artifact_id": "y3", "mime_type": "text/plain", "name": "config.yaml"},
        "code",
    ),
    ("code-moose-ext", {"artifact_id": "y4", "name": "input.i"}, "code"),
    ("code-python-mime", {"artifact_id": "y5", "mime_type": "text/x-python"}, "code"),
    ("code-toml-ext", {"artifact_id": "y6", "name": "pyproject.toml"}, "code"),
    ("code-xml-mime", {"artifact_id": "y7", "mime_type": "application/xml"}, "code"),
    ("code-dockerfile-basename", {"artifact_id": "y8", "name": "Dockerfile"}, "code"),
    (
        "code-cmake-plaintext-basename",
        {"artifact_id": "y9", "mime_type": "text/plain", "name": "CMakeLists.txt"},
        "code",
    ),
    ("code-log-ext", {"artifact_id": "y10", "name": "run.log"}, "code"),
    # Agent text parts default to "artifact.txt" + text/plain: must stay a report.
    ("report-plaintext-default-name", {"artifact_id": "r3", "mime_type": "text/plain", "name": "artifact.txt"}, "report"),
    ("file-zip", {"artifact_id": "f1", "mime_type": "application/octet-stream", "name": "logs.zip"}, "file"),
    ("file-inp", {"artifact_id": "f2", "name": "model.inp"}, "file"),
    ("ifc-mime", {"artifact_id": "i1", "mime_type": "application/ifc"}, "ifc"),
    ("ifc-tag", {"artifact_id": "i2", "tags": ["ifc"]}, "ifc"),
    ("exodus", {"artifact_id": "e1", "mime_type": "application/exodus"}, "mesh"),
    ("exodus-ext", {"artifact_id": "e2", "name": "mesh.exo"}, "mesh"),
    ("stl", {"artifact_id": "s1", "mime_type": "model/stl"}, "mesh"),
    ("mermaid", {"artifact_id": "m1", "mime_type": "text/mermaid"}, "mermaid"),
    ("reference", {"artifact_id": "ref1", "tags": ["reference"]}, "reference"),
    ("citation", {"artifact_id": "ref2", "tags": ["citation"]}, "reference"),
    ("thermal", {"artifact_id": "t1", "json_type": "prometheus.thermal_analysis.result.v1"}, "thermal"),
    ("image", {"artifact_id": "img1", "mime_type": "image/png"}, "image"),
    ("unknown", {"artifact_id": "u1", "mime_type": "application/x-proprietary"}, "unknown"),
    ("empty", {"artifact_id": "u2"}, "unknown"),
]


@pytest.mark.parametrize(
    "kind,artifact,expected_hint",
    _ARTIFACT_MATRIX,
    ids=[row[0] for row in _ARTIFACT_MATRIX],
)
def test_to_artifact_meta_render_hint(kind, artifact, expected_hint):
    """``to_artifact_meta`` shapes each artifact kind and derives the right hint."""
    meta = to_artifact_meta(artifact)
    assert meta is not None, f"{kind} artifact should not be dropped"
    assert meta.render_hint == expected_hint
    assert meta.artifact_id == artifact["artifact_id"]


def test_every_render_hint_value_is_reachable():
    """Every declared ``RenderHint`` value is produced by some artifact in the matrix.

    Guards against a hint being added to the contract with no classifier path (or a
    classifier path silently dropped) — the frontend viewer set and the backend
    classifier stay in lockstep.
    """
    from typing import get_args

    from app.contract import RenderHint

    declared = set(get_args(RenderHint))
    produced = {expected for _, _, expected in _ARTIFACT_MATRIX}
    assert declared == produced, f"unreached hints: {declared - produced}"


# --------------------------------------------------------------------------- #
# 3. normalize_followup_questions — every raw shape from _handle_needs_info
# --------------------------------------------------------------------------- #


def _one(raw: dict):
    fields = chat_service.normalize_followup_questions(_resp(status="needs_info", followup_questions=[raw]))
    assert len(fields) == 1
    return fields[0]


def test_followup_id_precedence_field_then_id_then_question():
    assert _one({"field": "fld", "id": "ident", "question": "Q?"}).id == "fld"
    assert _one({"id": "ident", "question": "Q?"}).id == "ident"
    assert _one({"question": "Q text"}).id == "Q text"


def test_followup_label_precedence_question_then_label():
    assert _one({"field": "f", "question": "What material?"}).label == "What material?"
    assert _one({"field": "f", "label": "Material"}).label == "Material"


def test_followup_input_type_precedence_and_default():
    assert _one({"field": "f", "type": "select"}).input_type == "select"
    assert _one({"field": "f", "input_type": "number"}).input_type == "number"
    assert _one({"field": "f"}).input_type == "text"


def test_followup_unknown_input_type_falls_back_to_text():
    # T-3: a nonstandard/empty agent type must not fail validation (which would turn the
    # whole needs_info turn into an error); it degrades to a text input like the old JSX.
    assert _one({"field": "f", "type": "radio"}).input_type == "text"
    assert _one({"field": "f", "type": "multiselect"}).input_type == "text"
    assert _one({"field": "f", "type": ""}).input_type == "text"
    assert _one({"field": "f", "type": "SELECT"}).input_type == "select"  # case-insensitive


def test_followup_required_defaults_true_and_is_overridable():
    assert _one({"field": "f"}).required is True
    assert _one({"field": "f", "required": False}).required is False


def test_followup_scalar_options_become_label_value_pairs():
    field = _one({"field": "f", "type": "select", "options": ["SS316", "SS347"]})
    assert field.options is not None
    assert [(o.label, o.value) for o in field.options] == [("SS316", "SS316"), ("SS347", "SS347")]


def test_followup_dict_options_preserved_and_label_defaults_to_value():
    field = _one({"field": "f", "type": "select", "options": [{"label": "L", "value": "v"}, {"value": "bare"}]})
    assert field.options is not None
    assert [(o.label, o.value) for o in field.options] == [("L", "v"), ("bare", "bare")]


def test_followup_default_and_description_mapped():
    field = _one({"field": "f", "default": "SS316", "description": "Pick an alloy"})
    assert field.default == "SS316"
    assert field.help == "Pick an alloy"


def test_followup_empty_questions_yield_empty_list():
    assert chat_service.normalize_followup_questions(_resp(status="needs_info")) == []
