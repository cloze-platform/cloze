import os
import time
import json
import requests
from typing import List, Dict, Optional, Tuple

# Ollama host configuration (default: localhost for local development)
OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')

# Provider clients (optional imports)
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

try:
    from google import genai
    from google.genai.types import GenerateContentConfig, SafetySetting, HarmCategory, HarmBlockThreshold
except ImportError:
    genai = None

class LLMInterface:
    """Unified interface for different LLM providers"""
    _provider_clients: Dict[str, object] = {}

    @classmethod
    def initialize_clients(cls):
        """Initialize provider clients based on available API keys"""
        # OpenAI
        openai_key = os.environ.get('OPENAI_API_KEY')
        if OpenAI and openai_key and openai_key.strip() and openai_key != 'your_openai_key_here':
            try:
                cls._provider_clients['openai'] = OpenAI(api_key=openai_key)
                print("✓ OpenAI client initialized successfully")
            except Exception as e:
                print(f"✗ Could not initialize OpenAI client: {e}")
        else:
            reasons = []
            if not OpenAI:
                reasons.append("OpenAI library not installed")
            if not openai_key:
                reasons.append("No API key found")
            elif not openai_key.strip():
                reasons.append("API key is empty")
            elif openai_key == 'your_openai_key_here':
                reasons.append("Using placeholder value")
            print(f"✗ OpenAI API key not configured or invalid: {', '.join(reasons)}")

        # Anthropic
        anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
        if Anthropic and anthropic_key and anthropic_key.strip() and anthropic_key != 'your_anthropic_key_here':
            try:
                cls._provider_clients['anthropic'] = Anthropic(api_key=anthropic_key)
                print("✓ Anthropic client initialized successfully")
            except Exception as e:
                print(f"✗ Could not initialize Anthropic client: {e}")
        else:
            reasons = []
            if not Anthropic:
                reasons.append("Anthropic library not installed")
            if not anthropic_key:
                reasons.append("No API key found")
            elif not anthropic_key.strip():
                reasons.append("API key is empty")
            elif anthropic_key == 'your_anthropic_key_here':
                reasons.append("Using placeholder value")
            print(f"✗ Anthropic API key not configured or invalid: {', '.join(reasons)}")

        # Google
        google_key = os.environ.get('GOOGLE_API_KEY')
        if genai and google_key and google_key.strip() and google_key != 'your_google_api_key_here':
            try:
                client = genai.Client(api_key=google_key)
                cls._provider_clients['google'] = client
                print("✓ Google client initialized successfully")
            except Exception as e:
                print(f"✗ Could not initialize Google client: {e}")
        else:
            print("✗ Google API key not configured or invalid")

        # Local Ollama
        try:
            ollama_url = f"{OLLAMA_HOST}/api/tags"
            response = requests.get(ollama_url, timeout=2)
            if response.status_code == 200:
                cls._provider_clients['local'] = True
                models = response.json().get('models', [])
                model_names = [m['name'] for m in models]
                print(f"✓ Ollama server detected at {OLLAMA_HOST} with models: {model_names}")
            else:
                print(f"✗ Ollama server at {OLLAMA_HOST} responded but with an error")
        except requests.exceptions.RequestException:
            print(f"✗ Ollama server not available at {OLLAMA_HOST}")

        print("\n=== LLM Client Status ===")
        print(f"Initialized providers: {list(cls._provider_clients.keys())}")
        for provider in ['openai', 'anthropic', 'google', 'local']:
            status = "✓ AVAILABLE" if provider in cls._provider_clients else "✗ NOT AVAILABLE"
            print(f"{provider}: {status}")
        print("========================\n")

    @classmethod
    def call_llm(cls, model, messages: List[Dict], system_prompt: Optional[str] = None, config_override: Optional[Dict] = None) -> Tuple[str, float]:
        """Call LLM with messages and return (response_text, response_time_sec)

        Args:
            model: Model object to use
            messages: List of message dicts with 'role' and 'content'
            system_prompt: Optional system prompt to prepend
            config_override: Optional config overrides (e.g., {'timeout': 180})
        """
        start_time = time.time()

        # Format messages with system prompt
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({'role': 'system', 'content': system_prompt})
        formatted_messages.extend(messages)

        config = json.loads(model.config or '{}')
        # Apply config overrides if provided
        if config_override:
            config.update(config_override)

        try:
            if model.provider == 'openai':
                client = cls._provider_clients.get('openai')
                if not client:
                    raise RuntimeError("OpenAI client not available")

                response = client.chat.completions.create(
                    model=model.model_identifier,
                    messages=formatted_messages,
                    temperature=config.get('temperature', 0.7),
                    max_tokens=config.get('max_tokens', 1000),
                )
                result = response.choices[0].message.content

            elif model.provider == 'anthropic':
                client = cls._provider_clients.get('anthropic')
                if not client:
                    raise RuntimeError("Anthropic client not available")

                # Extract system message
                system_msg = None
                anthropic_messages = []
                for msg in formatted_messages:
                    if msg['role'] == 'system':
                        system_msg = msg['content']
                    else:
                        anthropic_messages.append(msg)

                # Build request kwargs
                request_kwargs = {
                    'model': model.model_identifier,
                    'max_tokens': config.get('max_tokens', 1000),
                    'temperature': config.get('temperature', 0.7),
                    'messages': anthropic_messages,
                }

                # Newer Claude models (4.5+) require system as a list of content blocks
                if system_msg:
                    request_kwargs['system'] = [{"type": "text", "text": system_msg}]

                response = client.messages.create(**request_kwargs)
                # anthropic SDK returns list of content blocks
                result = response.content[0].text

            elif model.provider == 'google':
                client = cls._provider_clients.get('google')
                if not client:
                    raise RuntimeError("Google client not available")

                # Extract system prompt and format messages
                system_instruction = None
                gemini_messages = []
                for msg in formatted_messages:
                    if msg['role'] == 'system':
                        system_instruction = msg['content']
                    else:
                        role = 'model' if msg['role'] == 'assistant' else 'user'
                        gemini_messages.append({'role': role, 'parts': [{'text': msg['content']}]})

                safety_settings = [
                    SafetySetting(category=HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=HarmBlockThreshold.OFF),
                    SafetySetting(category=HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=HarmBlockThreshold.OFF),
                    SafetySetting(category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=HarmBlockThreshold.OFF),
                    SafetySetting(category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=HarmBlockThreshold.OFF),
                ]

                gen_config = GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=config.get('temperature', 0.7),
                    max_output_tokens=config.get('max_tokens', 8192),
                    safety_settings=safety_settings,
                )

                # Retry with exponential backoff for transient errors (503, rate limits)
                max_retries = 3
                response = None
                for attempt in range(max_retries):
                    try:
                        response = client.models.generate_content(
                            model=model.model_identifier,
                            contents=gemini_messages,
                            config=gen_config,
                        )
                        break
                    except Exception as retry_err:
                        err_str = str(retry_err)
                        if attempt < max_retries - 1 and ('503' in err_str or 'UNAVAILABLE' in err_str or '429' in err_str or 'RESOURCE_EXHAUSTED' in err_str):
                            wait = (2 ** attempt) + 1  # 1s, 3s, 5s
                            time.sleep(wait)
                            continue
                        raise

                # Handle blocked or empty responses
                if not response or not response.candidates:
                    cls._dump_gemini_safety_block(model, formatted_messages, response, config)
                    raise RuntimeError("Gemini returned no response candidates.")

                candidate = response.candidates[0]
                finish_reason = getattr(candidate, 'finish_reason', None)

                # Try to extract text even from truncated responses
                parts = getattr(getattr(candidate, 'content', None), 'parts', None)
                if parts:
                    result = response.text
                elif finish_reason and 'SAFETY' in str(finish_reason):
                    cls._dump_gemini_safety_block(model, formatted_messages, response, config)
                    raise RuntimeError(
                        f"Gemini blocked this response (finish_reason: {finish_reason}). "
                        "This may occur with sensitive clinical content. Try rephrasing."
                    )
                else:
                    cls._dump_gemini_safety_block(model, formatted_messages, response, config)
                    raise RuntimeError(
                        f"Gemini returned an empty response (finish_reason: {finish_reason})."
                    )

            elif model.provider == 'local':
                response = requests.post(
                    model.api_endpoint,
                    json={
                        'model': model.model_identifier,  # Required by Ollama
                        'messages': formatted_messages,
                        'temperature': config.get('temperature', 0.7),
                        'max_tokens': config.get('max_tokens', 1000),
                        'stream': False  # Disable streaming for simpler response handling
                    },
                    timeout=config.get('timeout', 250),  # Use custom timeout if provided (250s for CPU inference)
                )
                response.raise_for_status()
                result = response.json()['choices'][0]['message']['content']

            else:
                raise ValueError(f"Unknown provider: {model.provider}")

        except Exception as e:
            cls._dump_error_debug(model, formatted_messages, e, config)
            # Show a friendly message to the user, not the raw error
            err_str = str(e)
            if '503' in err_str or 'UNAVAILABLE' in err_str:
                result = "I'm temporarily unavailable due to high demand. Please try sending your message again in a moment."
            elif '429' in err_str or 'RESOURCE_EXHAUSTED' in err_str:
                result = "I'm receiving too many requests right now. Please wait a moment and try again."
            elif 'SAFETY' in err_str or 'blocked' in err_str.lower():
                result = "I wasn't able to generate a response to that. Could you try rephrasing?"
            else:
                result = "Something went wrong on my end. Please try again, and if the problem persists, let your provider know."

        response_time = time.time() - start_time
        return result, response_time

    @classmethod
    def _dump_gemini_safety_block(cls, model, messages, response, config):
        """Write detailed Gemini safety block info to debug file."""
        from pathlib import Path

        error_dir = Path(__file__).parent.parent.parent / 'instance' / 'llm_errors'
        error_dir.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime('%Y%m%d_%H%M%S')
        filepath = error_dir / f"{timestamp}_gemini_safety_block.txt"

        lines = [
            "Gemini Safety Block Debug Dump",
            f"{'=' * 60}",
            f"Timestamp:  {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Model:      {model.model_identifier}",
            f"Config:     {json.dumps(config, indent=2)}",
            "",
        ]

        # Response details
        try:
            lines.append(f"Candidates: {len(response.candidates) if response.candidates else 0}")
            if response.candidates:
                for j, candidate in enumerate(response.candidates):
                    lines.append(f"  Candidate {j}:")
                    lines.append(f"    finish_reason: {candidate.finish_reason}")
                    safety_ratings = getattr(candidate, 'safety_ratings', None)
                    if safety_ratings:
                        lines.append("    safety_ratings:")
                        for rating in safety_ratings:
                            cat = getattr(rating, 'category', 'unknown')
                            prob = getattr(rating, 'probability', None) or getattr(rating, 'blocked', 'unknown')
                            lines.append(f"      {cat}: {prob}")
            prompt_feedback = getattr(response, 'prompt_feedback', None)
            if prompt_feedback:
                lines.append("")
                lines.append(f"Prompt Feedback: {prompt_feedback}")
        except Exception as e:
            lines.append(f"Error reading response: {e}")

        # Full messages
        lines.append("")
        lines.append(f"{'=' * 60}")
        lines.append(f"MESSAGES ({len(messages)} total)")
        lines.append(f"{'=' * 60}")
        for i, msg in enumerate(messages):
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            lines.append("")
            lines.append(f"--- Message {i + 1} [{role}] ({len(content)} chars) ---")
            lines.append(content)

        try:
            filepath.write_text('\n'.join(lines), encoding='utf-8')
            print(f"Gemini safety block dump written to: {filepath}")
        except Exception as e:
            print(f"Failed to write safety block dump: {e}")

    @classmethod
    def _dump_error_debug(cls, model, messages, error, config):
        """Write a debug dump to instance/llm_errors/ when an LLM call fails."""
        import traceback
        from pathlib import Path

        error_dir = Path(__file__).parent.parent.parent / 'instance' / 'llm_errors'
        error_dir.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{model.provider}_{model.model_identifier.replace('/', '_')}.txt"
        filepath = error_dir / filename

        lines = [
            "LLM Error Debug Dump",
            f"{'=' * 60}",
            f"Timestamp:  {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Provider:   {model.provider}",
            f"Model:      {model.model_identifier}",
            f"Model Name: {model.name}",
            f"Config:     {json.dumps(config, indent=2)}",
            "",
            f"Error Type: {type(error).__name__}",
            f"Error:      {str(error)}",
            "",
            "Traceback:",
            traceback.format_exc(),
            "",
            f"{'=' * 60}",
            f"MESSAGES ({len(messages)} total)",
            f"{'=' * 60}",
        ]

        for i, msg in enumerate(messages):
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            lines.append("")
            lines.append(f"--- Message {i + 1} [{role}] ({len(content)} chars) ---")
            lines.append(content)

        # If it's a Gemini safety block, try to extract safety ratings
        try:
            if hasattr(error, '__cause__') and error.__cause__:
                lines.append("")
                lines.append(f"{'=' * 60}")
                lines.append("UNDERLYING CAUSE")
                lines.append(str(error.__cause__))
        except Exception:
            pass

        # Try to get the raw response object for Gemini
        try:
            import inspect
            frame = inspect.currentframe()
            # Walk up to find 'response' variable
            caller_locals = frame.f_back.f_back.f_locals if frame else {}
            raw_response = caller_locals.get('response')
            if raw_response and hasattr(raw_response, 'candidates'):
                lines.append("")
                lines.append(f"{'=' * 60}")
                lines.append("RAW RESPONSE")
                lines.append(f"Candidates: {len(raw_response.candidates) if raw_response.candidates else 0}")
                if raw_response.candidates:
                    for j, candidate in enumerate(raw_response.candidates):
                        lines.append(f"  Candidate {j}:")
                        lines.append(f"    finish_reason: {candidate.finish_reason}")
                        if hasattr(candidate, 'safety_ratings') and candidate.safety_ratings:
                            lines.append("    safety_ratings:")
                            for rating in candidate.safety_ratings:
                                lines.append(f"      {rating.category}: {rating.probability}")
                if hasattr(raw_response, 'prompt_feedback'):
                    lines.append(f"  prompt_feedback: {raw_response.prompt_feedback}")
        except Exception:
            pass

        try:
            filepath.write_text('\n'.join(lines), encoding='utf-8')
            print(f"LLM error debug dump written to: {filepath}")
        except Exception as write_err:
            print(f"Failed to write error dump: {write_err}")
