# This file is part of Prometheus
# https://inl.gov/super-intelligence/prometheus/
#
# Copyright 2026 Battelle Energy Alliance, LLC
# All rights reserved, see NOTICE.txt for full restrictions
# https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
#
# Licensed under the MIT License, please see LICENSE for details
# https://github.com/idaholab/prometheus_core/blob/main/LICENSE
#
# SPDX-License-Identifier: MIT

"""
Form Filler Agent - Extract structured data from natural language using JSON schemas.

This agent:
1. Auto-extracts field values from context text using the configured LLM
2. Supports multi-turn conversation for missing fields
3. Accepts both structured form answers and natural language replies
4. Returns A2A-compliant responses with followup_questions when data is missing
"""

import json
import os
import uuid
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import redis
from prometheus_api.agent import PrometheusAgent
from prometheus_api.llm_client import LLMConfig
from prometheus_api.redis_utils import create_redis_client
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events import EventQueue

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
REDIS_URL = os.getenv("REDIS_URL")
STATE_TTL_SECONDS = 3600  # 1 hour TTL for conversation state


class FormFillerAgent(PrometheusAgent):
    """
    Form Filler Agent.

    Extracts structured data from natural language context using JSON schemas.
    Auto-populates fields from provided context, then asks for missing values
    via both structured forms and natural language conversation.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._redis_client = None

    @property
    def redis_client(self) -> redis.Redis:
        """Lazy initialization of Redis client."""
        if self._redis_client is None:
            self._redis_client = create_redis_client(REDIS_URL, ping=False)
        return self._redis_client

    def get_state(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve conversation state from Redis."""
        key = f"form_filler:{conversation_id}"
        data = self.redis_client.get(key)
        if data:
            return json.loads(data)
        return None

    def save_state(self, conversation_id: str, state: Dict[str, Any]) -> None:
        """Save conversation state to Redis with TTL."""
        key = f"form_filler:{conversation_id}"
        self.redis_client.set(key, json.dumps(state), ex=STATE_TTL_SECONDS)

    def initialize_state(
        self,
        conversation_id: str,
        context: str,
        schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize a new conversation state."""
        state = {
            "conversation_id": conversation_id,
            "context": context,
            "schema": schema,
            "extracted_values": {},
            "initial_extraction_done": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.save_state(conversation_id, state)
        return state

    def extract_json_from_text(self, text: str) -> Optional[Dict]:
        """Extract JSON from text that may contain markdown code blocks."""
        # Try to find JSON in code blocks first
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find raw JSON object
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    async def extract_initial_values(
        self,
        state: Dict[str, Any],
        a2a_context: RequestContext,
    ) -> Dict[str, Any]:
        """Use the configured LLM to extract field values from context."""
        context = state["context"]
        schema = state["schema"]
        properties = schema.get("properties", {})

        if not properties:
            state["initial_extraction_done"] = True
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            return state

        # Build extraction prompt
        fields_description = []
        for field_name, field_schema in properties.items():
            field_type = field_schema.get("type", "string")
            description = field_schema.get("description", "")
            enum_values = field_schema.get("enum", [])

            field_desc = f"- {field_name} ({field_type})"
            if description:
                field_desc += f": {description}"
            if enum_values:
                field_desc += f" [allowed values: {', '.join(str(v) for v in enum_values)}]"
            fields_description.append(field_desc)

        prompt = f"""You are a data extraction specialist. Extract values for the following fields from the given context.

CONTEXT:
{context}

FIELDS TO EXTRACT:
{chr(10).join(fields_description)}

Return a JSON object with field names as keys and extracted values. Only include fields where you found a clear value in the context. Use null for fields where no value was found.

For numeric fields, extract numbers only (no units).
For enum fields, use the exact allowed value if mentioned.

        Return ONLY the JSON object, no explanation:"""

        try:
            llm_config = LLMConfig.from_env()
            async with self.llm_client(a2a_context, config=llm_config) as llm:
                response = await llm.medium(prompt, max_tokens=1024)

            response_text = response.text
            extracted = self.extract_json_from_text(response_text)

            if extracted:
                # Filter out null values and validate against schema
                for field_name, value in extracted.items():
                    if value is not None and field_name in properties:
                        # Type coercion
                        field_schema = properties[field_name]
                        field_type = field_schema.get("type", "string")

                        if field_type == "number" and not isinstance(value, (int, float)):
                            try:
                                value = float(value)
                            except (ValueError, TypeError):
                                continue

                        if field_type == "integer" and not isinstance(value, int):
                            try:
                                value = int(value)
                            except (ValueError, TypeError):
                                continue

                        # Enum validation
                        enum_values = field_schema.get("enum", [])
                        if enum_values and value not in enum_values:
                            continue

                        state["extracted_values"][field_name] = value

            logger.info(f"Extracted {len(state['extracted_values'])} form value(s) from initial context")

        except Exception as e:
            logger.error(f"Error extracting initial values: {e}")

        state["initial_extraction_done"] = True
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        return state

    def process_form_input(
        self,
        state: Dict[str, Any],
        followup_answers: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process structured form input answers."""
        schema = state["schema"]
        properties = schema.get("properties", {})

        for field_name, value in followup_answers.items():
            if field_name in properties and value is not None:
                field_schema = properties[field_name]
                field_type = field_schema.get("type", "string")

                # Type coercion
                if field_type == "number" and not isinstance(value, (int, float)):
                    try:
                        value = float(value)
                    except (ValueError, TypeError):
                        continue

                if field_type == "integer" and not isinstance(value, int):
                    try:
                        value = int(value)
                    except (ValueError, TypeError):
                        continue

                state["extracted_values"][field_name] = value

        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        return state

    async def process_nl_input(
        self,
        state: Dict[str, Any],
        query: str,
        a2a_context: RequestContext,
    ) -> Dict[str, Any]:
        """Use the configured LLM to parse natural language into field values."""
        schema = state["schema"]
        properties = schema.get("properties", {})
        current_values = state["extracted_values"]

        # Find missing fields
        required = schema.get("required", [])
        missing_fields = [f for f in required if f not in current_values]

        if not missing_fields:
            # All required fields filled
            return state

        # Build extraction prompt for missing fields
        fields_description = []
        for field_name in missing_fields:
            if field_name in properties:
                field_schema = properties[field_name]
                field_type = field_schema.get("type", "string")
                description = field_schema.get("description", "")
                enum_values = field_schema.get("enum", [])

                field_desc = f"- {field_name} ({field_type})"
                if description:
                    field_desc += f": {description}"
                if enum_values:
                    field_desc += f" [allowed values: {', '.join(str(v) for v in enum_values)}]"
                fields_description.append(field_desc)

        prompt = f"""You are a data extraction specialist. Extract values from the user's natural language response.

ORIGINAL CONTEXT:
{state["context"]}

USER'S RESPONSE:
{query}

FIELDS WE NEED:
{chr(10).join(fields_description)}

ALREADY EXTRACTED:
{json.dumps(current_values, indent=2)}

Return a JSON object with field names as keys for any values you can extract from the user's response.
Only include fields where you found a clear value. Use null for fields where no value was found.

        Return ONLY the JSON object, no explanation:"""

        try:
            llm_config = LLMConfig.from_env()
            async with self.llm_client(a2a_context, config=llm_config) as llm:
                response = await llm.medium(prompt, max_tokens=1024)

            response_text = response.text
            extracted = self.extract_json_from_text(response_text)

            if extracted:
                for field_name, value in extracted.items():
                    if value is not None and field_name in properties:
                        field_schema = properties[field_name]
                        field_type = field_schema.get("type", "string")

                        # Type coercion
                        if field_type == "number" and not isinstance(value, (int, float)):
                            try:
                                value = float(value)
                            except (ValueError, TypeError):
                                continue

                        if field_type == "integer" and not isinstance(value, int):
                            try:
                                value = int(value)
                            except (ValueError, TypeError):
                                continue

                        # Enum validation
                        enum_values = field_schema.get("enum", [])
                        if enum_values and value not in enum_values:
                            continue

                        state["extracted_values"][field_name] = value

            logger.info(f"Form state now contains {len(state['extracted_values'])} extracted value(s)")

        except Exception as e:
            logger.error(f"Error processing NL input: {e}")

        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        return state

    def get_missing_required_fields(self, state: Dict[str, Any]) -> List[str]:
        """Get list of required fields that are still missing."""
        schema = state["schema"]
        required = schema.get("required", [])
        current_values = state["extracted_values"]

        return [f for f in required if f not in current_values]

    def generate_followup_questions(
        self,
        state: Dict[str, Any],
        missing_fields: List[str]
    ) -> List[Dict[str, Any]]:
        """Generate followup questions for missing fields."""
        schema = state["schema"]
        properties = schema.get("properties", {})
        current_values = state["extracted_values"]

        questions = []

        for field_name in missing_fields:
            if field_name not in properties:
                continue

            field_schema = properties[field_name]
            field_type = field_schema.get("type", "string")
            description = field_schema.get("description", "")
            enum_values = field_schema.get("enum", [])
            minimum = field_schema.get("minimum")
            maximum = field_schema.get("maximum")

            # Build question
            question_text = description or f"What is the {field_name.replace('_', ' ')}?"

            # Determine question type
            if enum_values:
                q_type = "select"
                options = enum_values
            elif field_type in ("number", "integer"):
                q_type = "number"
                options = None
            else:
                q_type = "text"
                options = None

            question = {
                "field": field_name,
                "question": question_text,
                "type": q_type,
                "required": field_name in schema.get("required", []),
            }

            if options:
                question["options"] = options

            if minimum is not None or maximum is not None:
                question["validation"] = {}
                if minimum is not None:
                    question["validation"]["minimum"] = minimum
                if maximum is not None:
                    question["validation"]["maximum"] = maximum

            # Include current value if partially extracted
            if field_name in current_values:
                question["current_value"] = current_values[field_name]

            # Extract unit from description if present (e.g., "Temperature in °C")
            if description:
                unit_patterns = [
                    r'\(([^)]+)\)$',  # (°C)
                    r'in\s+(\S+)$',    # in °C
                    r'\[([^\]]+)\]$',  # [MPa]
                ]
                for pattern in unit_patterns:
                    match = re.search(pattern, description)
                    if match:
                        question["unit"] = match.group(1)
                        break

            questions.append(question)

        return questions

    async def _execute(
        self,
        params: Dict[str, Any],
        a2a_context: RequestContext,
        event_queue: EventQueue,
    ) -> Dict[str, Any]:
        """
        Process the form filling request.

        Handles initial extraction, form input, and natural language input.
        Returns A2A-compliant response with status and followup_questions when needed.
        """
        context = params.get("context", "")
        schema = params.get("schema", {})
        conversation_id = a2a_context.context_id or params.get("conversation_id") or str(uuid.uuid4())
        followup_answers = params.get("followup_answers")
        query = params.get("query")

        # Validate required params for new conversations
        if not context and not followup_answers and not query:
            return {
                "status": "error",
                "error": "Either 'context' (for new conversation) or 'followup_answers'/'query' (for continuation) is required",
                "conversation_id": conversation_id,
            }

        # Send status update
        await self.send_status_update(context=a2a_context, event_queue=event_queue)

        # Get or create state
        state = self.get_state(conversation_id)

        if not state:
            # New conversation - need context and schema
            if not context or not schema:
                return {
                    "status": "error",
                    "error": "Both 'context' and 'schema' are required for new conversations",
                    "conversation_id": conversation_id,
                }
            state = self.initialize_state(conversation_id, context, schema)
        else:
            # If new context/schema provided, update them
            if context:
                state["context"] = context
            if schema:
                state["schema"] = schema

        # Process input based on type
        if followup_answers:
            logger.info(f"Processing {len(followup_answers)} structured form answer(s)")
            state = self.process_form_input(state, followup_answers)
        elif query:
            logger.info("Processing natural-language form input")
            state = await self.process_nl_input(state, query, a2a_context)
        elif not state.get("initial_extraction_done"):
            logger.info("Performing initial extraction")
            state = await self.extract_initial_values(state, a2a_context)

        # Save updated state
        self.save_state(conversation_id, state)

        # Check completeness
        missing = self.get_missing_required_fields(state)

        if not missing:
            # All required fields filled - return completed result
            logger.info(f"Form complete with {len(state['extracted_values'])} value(s)")

            return {
                "status": "completed",
                "conversation_id": conversation_id,
                "filled_data": state["extracted_values"],
                "schema": state["schema"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "agent": "Form Filler Agent",
            }
        else:
            # Still missing fields - generate followup questions
            logger.info(f"Missing fields: {missing}")
            questions = self.generate_followup_questions(state, missing)

            return {
                "status": "needs_info",
                "conversation_id": conversation_id,
                "followup_questions": questions,
                "partial_data": state["extracted_values"],
                "missing_fields": missing,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "agent": "Form Filler Agent",
            }


if __name__ == "__main__":
    # Create and run the agent
    agent = FormFillerAgent(agent_name="Form Filler Agent")
    agent.run()
