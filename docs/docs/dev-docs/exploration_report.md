# Technical Exploration Report: Prometheus Frontend + Client-Agent A2A Integration

**Generated:** 2026-03-13
**Scope:** Deep analysis of Chainlit frontend, client-agent A2A interface, and gap analysis for direct integration

---

## 1. Chainlit Message Flow

### Current Flow (via Old FastAPI Backend)

**User input → Message Handler → Backend HTTP → Response → Rendered Element**

#### 1.1 Entry Point: `main.py:on_message()`

```python
@cl.on_message
async def on_message(message: cl.Message):
    await message_handler(message)
```

- Chainlit framework calls this hook whenever user submits text or files
- Message object contains `.content` (text) and `.elements` (uploaded files)

#### 1.2 Message Handler (`message_handler.py:15-125`)

The handler performs branching logic based on content type:

**Path A: File Uploads (Exodus, IFC, PDF)**
- Checks file extension in `message.elements`
- For Exodus files (`.exo`, `.e`): calls `process_exodus_upload(Path)` → returns dataset object → sends viewer element
- For IFC files (`.ifc`): calls `process_ifc_upload(Path)` → converts to `IFCViewer` element
- For PDF files: wraps in `cl.Pdf()` element
- If file upload only (no text), returns early

**Path B: Text Query (with or without files)**

```python
# Line 101-115
payload = {"message": message.content, "user_id": "user_123", "context": {}, "files": []}

response = requests.post(
    f"{settings.platform_url}/api/chat",
    json=payload,
    headers={"Authorization": "Bearer d8Q0ICXp1AUcGH0mLbkG-lgsUX6f_5RY7pu3KRrHUAE"}
)
data = response.json()
```

**Current Backend Response Types:**
1. **`type == "workflow"`**: Triggers demo workflow streaming (lines 118-120)
   - Calls `_run_demo_workflow(message.content, session_id, workflow_path="/api/demo/workflow/run")`
   - **Streaming Implementation:** Uses `httpx.AsyncClient.stream()` with `aiter_lines()`
   - Parses SSE-like JSON events: `{"event_type": "workflow_start|step_start|step_complete|workflow_complete"}`
   - Renders `cl.Step()` objects for each agent step with input/output
   - Fetches artifacts from `/api/demo/ifc` and `/api/demo/ifc-download` endpoints

2. **`type == "fmea_workflow"`**: Similar to workflow but with different workflow_path

3. **Default (text response)**: Sends simple text response from backend LLM

#### 1.3 Data Shapes (Current)

**Chat Request to Backend:**
```json
{
  "message": "Design a Rankine cycle...",
  "user_id": "user_123",
  "context": {},
  "files": []
}
```

**Chat Response from Backend (demo pattern):**
```json
{
  "type": "workflow",
  "session_id": "uuid",
  "response": "Starting workflow...",
  "workflow_id": "wf_..."
}
```

**Workflow Event Stream (SSE lines):**
```json
{"event_type": "workflow_start", "total_steps": 3}
{"event_type": "step_start", "agent": "Research Agent", "prompt": "...", "step_index": 0, "total_steps": 3}
{"event_type": "step_complete", "response": "...", "artifact_url": "/api/demo/ifc"}
{"event_type": "workflow_complete"}
```

#### 1.4 Artifact Handling

- Backend returns artifact URLs (`/api/demo/ifc`, `/api/demo/ifc-download`)
- Frontend fetches these URLs and renders via specialized viewers
- Artifacts are ephemeral (not persisted in conversation)

---

## 2. A2A Streaming Interface (Client-Agent)

### 2.1 A2A Protocol Overview

The client-agent uses the standard **Agent-to-Agent (A2A) JSON-RPC 2.0** protocol over HTTP POST.

**Endpoint:** `POST /{agent-url}` (typically `http://localhost:8000`)

### 2.2 Request Shape (`tool_discovery.py:212-236`)

```python
message = {
    "jsonrpc": "2.0",
    "id": request_id,  # UUID for request tracking
    "method": "message/send",
    "params": {
        "message": {
            "messageId": message_id,
            "role": "user",
            "parts": [
                {
                    "type": "text",
                    "text": json.dumps(kwargs)  # Parameters as JSON string in message text
                }
            ]
        },
        "configuration": {
            "blocking": True,  # Wait for completion before returning
        },
        "context": {
            "skillId": skill_id,
            "conversationId": kwargs.get("conversation_id", str(uuid.uuid4()))
        }
    }
}
```

**Key Points:**
- Parameters are passed as JSON-encoded text in `parts[0].text`
- `conversationId` must be provided by caller (comes from frontend `conversation_id`)
- `blocking: True` means synchronous execution (client waits for completion)
- Uses Bearer token auth: `Authorization: Bearer {agent_secret}`

### 2.3 Response Shape (agent.py:56-76)

```python
class ConversationResponse(BaseModel):
    conversation_id: str
    status: str  # "needs_info" | "plan_ready" | "executing" | "completed" | "recommendation" | "answer"
    message: Optional[str] = None

    # When status == "needs_info"
    followup_questions: Optional[List[Dict]] = None

    # When status == "plan_ready"
    plan: Optional[Dict] = None

    # When status == "completed"
    report: Optional[str] = None
    tool_results: Optional[Dict] = None

    # When status == "recommendation" or "answer"
    response_text: Optional[str] = None
    recommended_materials: Optional[List[str]] = None
    artifacts: Optional[List[Dict[str, Any]]] = None
    message_metadata: Optional[Dict[str, Any]] = None
```

**Response Lifecycle:**
1. **`needs_info`**: Agent needs user input; returns `followup_questions`
2. **`plan_ready`**: Planning phase complete; returns `plan` for user approval
3. **`executing`**: Plan approved, now executing (not used in blocking mode)
4. **`completed`**: Final result with `report` and `tool_results`
5. **`recommendation`**: Alternative response type (similar to answer)
6. **`answer`**: Direct response with `response_text`

### 2.4 Conversation State Management (agent.py:78-110)

```python
class AgentState(TypedDict):
    # Multi-turn tracking
    conversation_id: Optional[str]
    user_query: Optional[str]
    conversation_history: List[Dict]  # Full history across turns

    # Routing & planning
    routing_decision: Optional[Dict[str, Any]]
    plan: Optional[Dict]
    missing_info: List[str]
    awaiting_approval: bool

    # Query parameters
    material_id: Optional[str]
    analysis_types: Optional[List[str]]
    context: Optional[Dict[str, Any]]
    question: Optional[str]

    # Memory & artifacts
    retrieved_memories: Optional[List[Dict[str, Any]]]
    extracted_factoids: Optional[List[str]]
    num_memories_retrieved: Optional[int]
    num_memories_stored: Optional[int]

    # Results
    tool_results: Dict[str, Any]
    final_report: Optional[str]
```

**Persistence:** Stored in Redis via `memory_manager.store_conversation(conv_id, state)`

### 2.5 Streaming via A2A (tool_discovery.py:186-383)

**Current Status:** **BLOCKING ONLY** (no streaming in current implementation)

```python
# timeout_seconds = 900.0  # 15 minutes
async with httpx.AsyncClient(timeout=timeout_seconds) as client:
    response = await client.post(agent_url, json=message, headers=headers)
    result = response.json()
```

**Important:** The client-agent calls downstream agents with `blocking=True`, meaning it waits for the full response. The **frontend cannot stream events from specialist agents directly** — only the client-agent's planning/execution status.

**Response extraction logic (lines 261-373):**
1. Check `result.status.message.parts[]` for final response
2. Fall back to `result.artifacts[]` for structured payloads
3. Scan `result.history[]` in reverse for last agent message with JSON result
4. Return raw result if no JSON found

**Artifact extraction:**
- Looks for objects with `uri`, `name`, `description` fields
- Merges artifact references into response for rendering

### 2.6 Conversation Request Structure (agent.py:45-54)

```python
class ConversationRequest(BaseModel):
    query: Optional[str] = ""                    # Natural language query
    conversation_id: Optional[str] = None        # Multi-turn identifier
    followup_answers: Optional[Dict] = None      # Answers to prior questions
    plan_approved: Optional[bool] = False        # Approval gate
    artifacts: Optional[List[Dict[str, Any]]] = None  # Artifact catalog
    workflow_id: Optional[str] = None            # Explicit workflow selection
    workflow_version: Optional[str] = None
    selection_source: Optional[str] = None       # "catalog|matcher|dynamic_router"
```

**Flow:**
1. **Turn 1:** `query="Design a reactor..."`, `conversation_id=None` → agent creates new conv_id, returns response
2. **Turn 2+:** Same `conversation_id`, `query="...follow-up..."`, agent reads prior state from Redis
3. **Approval:** Set `plan_approved=True` to execute pending plan
4. **Artifacts:** Pass artifact metadata (not content) for parameter resolution

---

## 3. PrometheusAgent Base Class

### 3.1 Architecture (base.py:340-870)

`PrometheusAgent` is a wrapper around the A2A protocol that:
1. Loads agent metadata from `agent_card.json`
2. Sets up HTTP server with Bearer token auth
3. Manages task execution and status updates
4. Provides artifact reference registry

### 3.2 Executor Lifecycle (base.py:66-159)

```python
class PrometheusAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # 1. Extract parameters from message
        params = self._extract_params(context)

        # 2. Send "working" status
        await self._emit_status(
            context, event_queue,
            state=TaskState.working, final=False
        )

        # 3. Call agent-specific _execute() implementation
        result = await self._execute(params, context, tracked_queue)

        # 4. Send result artifact (if not already sent)
        if not tracked_queue.seen_artifact:
            await self._emit_json_artifact(context, event_queue, payload=result)

        # 5. Send completion status
        await self._emit_status(
            context, event_queue,
            state=TaskState.completed, final=True
        )
```

**Key Pattern:** Agents can emit their own artifacts + status during `_execute()`, and the executor skips automatic finalization if final status already sent (lines 123-144).

### 3.3 Status Updates (base.py:160-188)

```python
async def _emit_status(
    self,
    context: RequestContext,
    event_queue: EventQueue,
    state: TaskState,  # TaskState.working | completed | failed
    final: bool,
    message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    status_message = None
    if message:
        status_message = Message(
            messageId=str(uuid.uuid4()),
            role="agent",
            parts=[Part(root=TextPart(text=message))],
            contextId=context.context_id,
            taskId=context.task_id,
        )

    await event_queue.enqueue_event(
        TaskStatusUpdateEvent(
            taskId=context.task_id,
            contextId=context.context_id,
            final=final,
            status=TaskStatus(state=state, message=status_message),
            metadata=metadata,
        )
    )
```

**A2A Protocol:** Status updates are queued on the event_queue, which the A2A framework serializes and returns to caller.

### 3.4 Artifact Reference Registry (artifacts.py:47-111)

```python
@dataclass
class ArtifactReference:
    artifact_id: str
    conversation_id: str
    name: str
    description: str
    uri: str  # Location of actual file (filesystem, HTTP, DeepLynx, etc.)
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    producer_agent_id: Optional[str] = None
    created_at: str = field(default_factory=_utc_now_iso)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**Storage:**
- **Primary:** Redis (conversation-scoped hashes)
- **Fallback:** In-memory dict (when Redis unavailable)

**Helper Methods:**
```python
# Auto-registration in send_json_artifact
parsed_ref = self._payload_to_artifact_reference(
    payload,
    fallback_name=name,
    conversation_id=context.context_id,
    producer_agent_id=self.agent_name.lower()
)
if parsed_ref is not None:
    registered = self.register_artifact_reference(context, parsed_ref)
```

### 3.5 Helper Methods for Agents

**Status Updates:**
```python
await agent.send_status_update(
    context, event_queue,
    state=TaskState.working,
    message="Processing material data...",
    final=False
)
```

**Artifacts:**
```python
artifact_id = await agent.send_json_artifact(
    context, event_queue,
    payload={"analysis": result},
    name="analysis_result"
)

# Or for external files:
await agent.send_artifact_reference(
    context, event_queue,
    name="Generated CAD Model",
    description="3D mesh in OBJ format",
    uri="file:///tmp/mesh.obj",
    mime_type="model/obj"
)
```

---

## 4. Gap Analysis: Frontend → A2A Direct Integration

### 4.1 Things to REPLACE (Old Backend Calls → New A2A Calls)

#### Current: HTTP POST to `/api/chat`
```python
# Current (message_handler.py:104)
response = requests.post(
    f"{settings.platform_url}/api/chat",
    json={"message": message.content, "user_id": "user_123", ...},
    headers={"Authorization": "Bearer ..."}
)
```

#### New: A2A JSON-RPC POST to Client-Agent
```javascript
// Proposed (will be in new message_handler or chat utility)
const response = await fetch('http://localhost:8000', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + agentToken
  },
  body: JSON.stringify({
    jsonrpc: "2.0",
    id: requestId,
    method: "message/send",
    params: {
      message: {
        messageId: uuid(),
        role: "user",
        parts: [{
          type: "text",
          text: JSON.stringify({
            query: messageContent,
            conversation_id: convId,
            artifacts: artifactList  // Optional: pass artifact metadata
          })
        }]
      },
      configuration: { blocking: true },
      context: {
        skillId: "analyze_material",  // Or "coordinate_analysis"
        conversationId: convId
      }
    }
  })
})
```

**Key Changes:**
- Protocol: HTTP POST body → JSON-RPC 2.0 message/send
- Endpoint: FastAPI `/api/chat` → A2A server (port 8000)
- Auth: Bearer token in Authorization header (same pattern, different issuer)
- Request model: Simple flat payload → nested params/message structure
- Response model: `{type, response}` → `{conversation_id, status, ...}`

#### Current Workflow Streaming → New A2A Status Updates

**Current:** Uses `httpx.stream()` to read SSE-like events

**New:** Frontend polls or uses Server-Sent Events from A2A event stream

**NOTE:** Client-agent uses blocking mode, so no real-time streaming from specialist agents. Frontend gets one response per user turn.

### 4.2 Things to ADD

#### 1. Multi-Turn Conversation Management

```python
# Need to add in message_handler.py:
conversation_id = None  # Persist this across turns
artifacts_catalog = []  # Track available artifacts

async def message_handler(message):
    global conversation_id, artifacts_catalog

    if conversation_id is None:
        conversation_id = str(uuid.uuid4())

    # Build request
    request = ConversationRequest(
        query=message.content,
        conversation_id=conversation_id,
        artifacts=artifacts_catalog
    )

    # Call A2A agent
    response = await call_a2a_agent(
        agent_url="http://localhost:8000",
        request=request
    )

    # Extract artifacts for next turn
    if response.artifacts:
        artifacts_catalog = response.artifacts
```

#### 2. Streaming Protocol (Optional but Recommended)

**Option A: Polling**
- Frontend polls `/api/chat/{conversation_id}/status` every 1-2 seconds
- Returns: `{status, message, progress}`

**Option B: Server-Sent Events**
- Client-agent (or adaptor) exposes `GET /api/chat/{conversation_id}/stream`
- Streams: TaskStatusUpdateEvent, TaskArtifactUpdateEvent as newline-delimited JSON
- Better for long-running operations

**Option C: WebSocket**
- Upgrade frontend to WebSocket
- Bi-directional: frontend can cancel tasks mid-execution

#### 3. Bearer Token Configuration

```yaml
# config.yml - add new section
a2a-agent:
  url: "http://client-agent:8000"  # or env var AGENT_URL
  auth_token: "${AGENT_SECRET}"     # env var for Bearer token
```

#### 4. Conversation ID Persistence

```python
# In Chainlit session metadata
@cl.on_chat_start
async def on_chat_start():
    cl.user_session.set("conversation_id", str(uuid.uuid4()))
    # Load prior artifacts if session resumed
    cl.user_session.set("artifacts", [])

# In message_handler
async def message_handler(message):
    conv_id = cl.user_session.get("conversation_id")
    artifacts = cl.user_session.get("artifacts", [])

    # Make A2A call
    response = await call_a2a_client.send(
        query=message.content,
        conversation_id=conv_id,
        artifacts=artifacts
    )

    # Update session
    if response.artifacts:
        cl.user_session.set("artifacts", response.artifacts)
```

#### 5. Artifact Catalog Integration

```python
# In message_handler - handle artifacts in response
if response.artifacts:
    artifact_catalog = response.artifacts

    for artifact_meta in artifact_catalog:
        # Show available artifacts in UI
        # (artifact_meta = {artifact_id, name, uri, mime_type, ...})
        await cl.Message(
            content=f"Available: {artifact_meta['name']}",
            elements=[  # Optional: embed viewer if mime_type is known
                # defer to specialized handler
            ]
        ).send()
```

#### 6. Follow-up Questions & Plan Approval Gates

```python
# New response states to handle
if response.status == "needs_info":
    # Ask follow-up questions
    for q in response.followup_questions:
        action = await cl.AskActionMessage(
            content=q.get("question"),
            actions=[
                cl.Action(name="yes", label="Yes"),
                cl.Action(name="no", label="No"),
            ]
        ).send()

        followup_answers[q.get("id")] = action.get("name")

    # Re-invoke with answers
    response = await call_a2a_client.send(
        query=message.content,
        conversation_id=conv_id,
        followup_answers=followup_answers
    )

if response.status == "plan_ready":
    # Show plan, ask for approval
    plan_text = format_plan(response.plan)
    approval = await cl.AskActionMessage(
        content=plan_text,
        actions=[
            cl.Action(name="approve", label="Proceed"),
            cl.Action(name="reject", label="Modify Plan"),
        ]
    ).send()

    response = await call_a2a_client.send(
        query=message.content,
        conversation_id=conv_id,
        plan_approved=(approval.get("name") == "approve")
    )
```

### 4.3 Things to PRESERVE

#### All JSX Custom Elements
```javascript
// Keep exactly as-is; no protocol changes needed:
- DynamicForm.jsx (form rendering)
- ExodusViewer.jsx (VTK.js 3D visualization)
- IFCViewer.jsx (ThatOpen/OBC 3D visualization)
- MermaidViewer.jsx (diagram rendering)
- FollowUpSuggestions.jsx (quick action buttons)
```

These are Chainlit CustomElement components that receive props from Python. They don't call any backend APIs directly.

#### Authentication Flow
```python
# Keep Chainlit's built-in auth:
@cl.password_auth_callback
def auth_callback(username: str, password: str):
    for user in settings.local_users:
        if user.get("username") == username and user.get("password") == password:
            return cl.User(...)
    return None
```

This authenticates to Chainlit server, separate from A2A agent Bearer token.

#### File Upload Handling
```python
# Keep special handlers for Exodus, IFC, PDF uploads
if element.name.endswith((".exo", ".e")):
    dataset = await process_exodus_upload(Path(element.path))
    viewer = dataset.to_chainlit_element()
```

These don't need to change; they process files locally before sending query.

#### Settings/Configuration System
```yaml
# Keep config.yml structure, just add a2a-agent section:
platform-url: "http://localhost:8001"  # (deprecated, remove)
a2a-agent:
  url: "http://localhost:8000"
  auth_token: "${AGENT_SECRET}"
```

### 4.4 Things to REMOVE

#### 1. Old FastAPI Backend Entirely
```python
# DELETE: prometheus_platform/backend/
#   - main.py
#   - routers/chat.py
#   - routers/demo_workflow.py
#   - routers/demo.py
#   - orchestrator/
#   - models/
#   - etc.
```

**Reason:** All logic moves to client-agent; FastAPI becomes unused.

#### 2. Hardcoded Model/LLM in Settings
```yaml
# DELETE from config.yml:
model: "gpt-oss-120B"
openai_api_key: "..."
```

**Reason:** Model selection is now in client-agent's planner.

#### 3. Demo Data & Routes
```python
# DELETE:
# /api/demo/workflow/run (streaming workflow)
# /api/demo/workflow/status
# /api/demo/ifc
# /api/demo/ifc-download
# /api/demo/exodus
# /api/demo/autodone
```

**Reason:** Replaced by dynamic agent discovery and artifact registry.

#### 4. Polling/Status Endpoints
```python
# DELETE:
# /api/workflows/{id}/status
# /api/chat/status
```

**Reason:** Status now flows through A2A event queue (or via new `/api/chat/{conv_id}/stream` if SSE is added).

#### 5. `requests.post()` to Backend
```python
# DELETE from message_handler.py:104-115
response = requests.post(
    f"{settings.platform_url}/api/chat",  # ← this backend call
    ...
)
```

**Reason:** Replaced with A2A JSON-RPC call.

---

## 5. Registry Replacement Analysis

### 5.1 What Homemade Registry Does (registry/app.py:1-223)

**Core Functions:**

1. **Agent Registration**
   - `POST /agents/register` → Stores agent metadata + full `agent_card.json`
   - In-memory storage (not persistent)
   - Returns: registered agent entry with timestamp

2. **Agent Discovery**
   - `GET /agents` → List all registered agents
   - `GET /agents/{agent_id}` → Get single agent
   - `GET /agents/{agent_id}/card` → Get full agent card with skills

3. **Capability Discovery**
   - `GET /capabilities` → Flattened list of all skills from all agents
   - Returns: skill_id, agent_id, input_schema, expected_duration_seconds, requires_approval, etc.
   - `GET /capabilities/search?tag=X&query=Y` → Filter by tag or text

4. **Heartbeat/Health**
   - `POST /agents/{agent_id}/heartbeat` → Update last_seen timestamp
   - Agent liveness tracking (not enforced)

### 5.2 What litellm Proxy Provides

**litellm Proxy Configuration:**
```yaml
# config.yaml for litellm proxy
model_list:
  - model_name: "material-analyzer"
    litellm_params:
      model: "anthropic/claude-opus-4-6"
      api_base: "http://material-agent:8000"
      api_key: "${AGENT_SECRET}"

  - model_name: "workflow-orchestrator"
    litellm_params:
      model: "openai/gpt-4-turbo"
      api_base: "http://client-agent:8000"
      api_key: "${AGENT_SECRET}"
```

**Provided:**
- ✅ Model routing (by name)
- ✅ API key management (per model/agent)
- ✅ Load balancing (multiple instances)
- ✅ Rate limiting
- ✅ Logging/monitoring

**NOT Provided:**
- ❌ Skill-level discovery (skills are at agent level, not model level)
- ❌ Input schema validation/filtering
- ❌ Capability matching (routing based on skill metadata)
- ❌ Approval gate enforcement
- ❌ Artifact catalog management

### 5.3 Recommended Hybrid Approach

**Keep lightweight registry for A2A agents, use litellm for model proxying:**

```python
# prometheus_platform/registry/app.py (simplified)
@app.post("/agents/register")
async def register_agent(registration: AgentRegistration):
    """Register agent and sync to litellm config."""
    registered_agents[registration.agent_id] = registration.dict()

    # Update litellm proxy config
    model_entry = {
        "model_name": registration.agent_id,
        "litellm_params": {
            "model": f"a2a/{registration.agent_id}",  # Custom model identifier
            "api_base": registration.url,
            "api_key": os.getenv(f"AGENT_SECRET_{registration.agent_id}"),
        }
    }
    # Write to litellm config (or call litellm management API if available)

    return {"status": "registered"}

@app.get("/capabilities")
async def list_capabilities():
    """Return flattened skills with metadata for LLM-based routing."""
    capabilities = []
    for agent in registered_agents.values():
        for skill in agent.get("agent_card", {}).get("skills", []):
            capabilities.append({
                "skill_id": skill["id"],
                "agent_id": agent["agent_id"],
                "agent_url": agent["url"],
                "input_schema": skill.get("inputSchema", {}),
                "requires_approval": skill.get("requires_approval", False),
                "expected_duration_seconds": skill.get("expected_duration_seconds"),
                # ... other metadata
            })
    return {"capabilities": capabilities}
```

### 5.4 Gaps Remaining After Registry Replacement

| Feature | Current Registry | litellm | Solution |
|---------|------------------|---------|----------|
| Agent discovery | ✅ | ⚠️ (limited) | Keep registry, use for capability discovery only |
| Model proxying | ❌ | ✅ | Use litellm proxy for multi-model routing |
| Input schema validation | ✅ | ❌ | Add schema validator in client-agent planner |
| Approval gates | ✅ | ❌ | Implement in ConversationResponse.status |
| Artifact catalog | ✅ | ❌ | Use ArtifactRegistry in PrometheusAgent |
| Load balancing | ❌ | ✅ | Use litellm for specialist agents (future) |

**Recommendation:** Keep the registry service as-is for now. It's lightweight and handles capability discovery. litellm can be a future enhancement for multi-model scenarios, but it's not required for the MVP A2A integration.

---

## 6. Recommended A2A Endpoint URL & Auth Pattern

### 6.1 Endpoint Configuration

**Development:**
```yaml
# prometheus_platform/frontend/config.yml
a2a-agent:
  url: "http://localhost:8000"  # Client-Agent endpoint
  skill_id: "analyze_material"  # Default skill to invoke
```

**Production (Docker Compose):**
```yaml
# docker-compose.yml
services:
  client-agent:
    image: prometheus/client-agent:latest
    ports:
      - "8000:8000"
    environment:
      - AGENT_PORT=8000
      - REGISTRY_URL=http://registry:8000
      - MODEL_NAME=claude-opus-4-6
      - AGENT_SECRET=${AGENT_SECRET}  # Shared secret

  frontend:
    image: prometheus/frontend:latest
    ports:
      - "8500:8500"
    environment:
      - AGENT_URL=http://client-agent:8000
      - AGENT_SECRET=${AGENT_SECRET}
```

### 6.2 Bearer Token Auth Pattern

**Token Issuance:**
```python
# No changes needed; both use same mechanism:
# 1. Token stored in env var: AGENT_SECRET
# 2. Passed as: Authorization: Bearer ${AGENT_SECRET}
# 3. Validated by A2A framework middleware: BearerTokenMiddleware
```

**Token Validation (client-agent):**
```python
# From base.py middleware - already implemented
class BearerTokenMiddleware:
    def __call__(self, request: Request) -> Optional[Dict[str, Any]]:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        token = auth_header[7:]  # Strip "Bearer " prefix
        expected_token = os.getenv("AGENT_SECRET", "").strip()
        if token == expected_token:
            return {"authenticated": True}
        return None
```

### 6.3 Frontend Implementation

```python
# prometheus_platform/frontend/utils/a2a_client.py (new file)
import httpx
import json
import uuid
from typing import Dict, Any, Optional

async def call_agent(
    agent_url: str,
    query: str,
    conversation_id: str,
    agent_secret: str,
    artifacts: Optional[List[Dict]] = None,
    followup_answers: Optional[Dict] = None,
    plan_approved: Optional[bool] = False,
) -> Dict[str, Any]:
    """Call client-agent via A2A protocol."""

    request_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())

    # Build A2A request
    message = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/send",
        "params": {
            "message": {
                "messageId": message_id,
                "role": "user",
                "parts": [{
                    "type": "text",
                    "text": json.dumps({
                        "query": query,
                        "conversation_id": conversation_id,
                        "artifacts": artifacts or [],
                        "followup_answers": followup_answers,
                        "plan_approved": plan_approved,
                    })
                }]
            },
            "configuration": {"blocking": True},
            "context": {
                "skillId": "analyze_material",
                "conversationId": conversation_id,
            }
        }
    }

    # Call agent with Bearer token
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {agent_secret}",
    }

    async with httpx.AsyncClient(timeout=900.0) as client:
        response = await client.post(agent_url, json=message, headers=headers)
        response.raise_for_status()
        result = response.json()

    # Extract ConversationResponse from A2A result
    a2a_result = result.get("result", {})

    # Parse response (logic from tool_discovery.py:261-373)
    # Check status.message, then artifacts, then history
    # ... (same extraction logic)

    return parse_conversation_response(a2a_result)
```

### 6.4 Message Handler Integration

```python
# prometheus_platform/frontend/components/message_handler.py (updated)
import asyncio
from utils.a2a_client import call_agent
from utils.settings import settings

@cl.on_message
async def on_message(message: cl.Message):
    # File handling (unchanged)
    if message.elements:
        # ... existing file upload logic ...
        pass

    # Get or create conversation ID
    conversation_id = cl.user_session.get("conversation_id")
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
        cl.user_session.set("conversation_id", conversation_id)

    # Get artifact catalog from session
    artifacts_catalog = cl.user_session.get("artifacts", [])

    try:
        # Call A2A agent
        response = await call_agent(
            agent_url=settings.agent_url,  # "http://localhost:8000"
            query=message.content,
            conversation_id=conversation_id,
            agent_secret=settings.agent_secret,  # From env var
            artifacts=artifacts_catalog,
        )

        # Handle response based on status
        if response.status == "needs_info":
            # Show follow-up questions, recursively call with answers
            pass
        elif response.status == "plan_ready":
            # Show plan, ask for approval, recursively call with approval
            pass
        elif response.status == "completed" or response.status == "answer":
            # Display response + artifacts
            await cl.Message(content=response.response_text).send()

            # Update artifact catalog for next turn
            if response.artifacts:
                artifacts_catalog = response.artifacts
                cl.user_session.set("artifacts", artifacts_catalog)

    except Exception as e:
        await cl.Message(content=f"Error: {str(e)}").send()
```

---

## 7. Summary & Implementation Roadmap

### 7.1 What Changes in Chainlit Frontend

| Component | Current | New | Effort |
|-----------|---------|-----|--------|
| message_handler | POST to FastAPI `/api/chat` | POST to A2A `/message/send` | Low |
| Session state | None | conversation_id + artifacts_catalog | Low |
| Response handling | Parse `{type, response, workflow_id}` | Parse `{conversation_id, status, ...}` | Low |
| Multi-turn | Not supported | Fully supported via conv_id | Medium |
| Streaming | SSE events from `/api/demo/workflow/run` | No real-time streaming (blocking A2A) | Low (breaking change) |
| Settings | `platform_url` to FastAPI backend | `agent_url` to A2A agent | Low |

### 7.2 What Changes in Backend

| Component | Current | New | Effort |
|-----------|---------|-----|--------|
| FastAPI app | `/api/chat` → orchestration | DELETE ENTIRE APP | High (removal) |
| Registry | In-memory, no persistence | Keep as-is | None |
| Routing logic | FastAPI routes | Moved to client-agent planner | Done |
| Streaming | Custom SSE implementation | A2A status events | Done |

### 7.3 Critical Path Implementation

**Phase 1: Minimal A2A Integration (2 days)**
1. ✅ Parse ConversationRequest/Response in client-agent (already done)
2. ⚠️ Update message_handler.py to call A2A instead of FastAPI
3. ⚠️ Add conversation_id tracking to Chainlit session
4. ⚠️ Handle `status == "completed"` response type
5. ⚠️ Test with simple text queries

**Phase 2: Multi-Turn & Artifacts (2 days)**
1. ✅ Artifact registry already implemented in PrometheusAgent
2. ⚠️ Pass artifact catalog to A2A calls
3. ⚠️ Render artifact list in frontend
4. ⚠️ Test multi-turn conversation state persistence

**Phase 3: Approval Gates & Follow-ups (2 days)**
1. ⚠️ Handle `status == "needs_info"` → show AskActionMessage
2. ⚠️ Handle `status == "plan_ready"` → show plan, ask approval
3. ⚠️ Recursive call with followup_answers + plan_approved
4. ⚠️ Test approval flow end-to-end

**Phase 4: Remove Old Backend (1 day)**
1. Delete `prometheus_platform/backend/`
2. Delete demo routes from FastAPI
3. Update docker-compose to remove backend service
4. Test full stack with registry + client-agent + frontend

**Total: ~7 days**

### 7.4 Key Files to Modify

```
prometheus_platform/
├── frontend/
│   ├── components/message_handler.py           (MAJOR: replace backend calls)
│   ├── utils/a2a_client.py                     (NEW: A2A protocol wrapper)
│   ├── config.yml                              (MINOR: update settings)
│   ├── main.py                                 (MINOR: conversation ID init)
│   └── public/elements/*.jsx                   (NO CHANGES)
│
├── backend/                                     (DELETE ENTIRE FOLDER)
│
├── docs/
│   └── exploration_report.md                   (THIS FILE)
│
└── docs/
    └── A2A_INTEGRATION_GUIDE.md               (NEW: implementation guide)

multi_agent_testbed/
├── agents/client-agent/
│   └── agent.py                                (MINOR: already has ConversationRequest/Response)
│
├── registry/
│   └── app.py                                  (NO CHANGES: keep as-is)
│
└── prometheus_api/
    └── prometheus_api/agent/
        ├── base.py                             (NO CHANGES: already complete)
        └── artifacts.py                        (NO CHANGES: already complete)
```

---

## 8. References & Supporting Information

### 8.1 A2A Protocol Docs
- **File:** tool_discovery.py:186-236 (request structure)
- **File:** base.py:85-159 (executor + event flow)
- **Concepts:** Blocking mode, event queue, status updates

### 8.2 Artifact Handling
- **File:** artifacts.py (ArtifactReference data model)
- **File:** base.py:705-804 (send_json_artifact, send_artifact_reference)
- **Concepts:** Metadata-only references, Redis storage, artifact catalog

### 8.3 Frontend Elements (No Changes)
- **Files:** public/elements/*.jsx
- **Concepts:** Chainlit CustomElement API, props binding

### 8.4 Config & Deployment
- **File:** config.yml (frontend settings)
- **File:** agent_card.json (agent metadata)
- **Concepts:** Environment variable configuration, Docker Compose

---

**Report Complete**
*For implementation details, see IMPLEMENTATION_CHECKLIST.md*
