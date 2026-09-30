"""Interactive terminal chat with the locally configured Qwen model.

Testing interface only: the model is loaded once, conversation history is
kept in memory for the life of the process, and nothing is stored on disk.

Usage:
    python scripts/chat.py
    python scripts/chat.py --max-new-tokens 200 --temperature 0.5
    python scripts/chat.py --greedy --system "You are a concise assistant."

Commands inside the chat:
    /help       show commands
    /clear      forget the conversation and start over
    /history    print the conversation so far
    /settings   show model and generation settings
    /exit       quit (also /quit, Ctrl+D, or Ctrl+Z+Enter on Windows)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from transformers import TextStreamer

from regulus.config import ConfigError, GenerationConfig, Settings, load_settings
from regulus.inference import ChatSession, generate_chat, split_thinking
from regulus.model import ModelLoadError, environment_info, load_model, load_tokenizer

RULE = "-" * 50
HELP = """Commands:
  /help       show this message
  /clear      forget the conversation and start over
  /history    print the conversation so far
  /settings   show model and generation settings
  /exit       quit (also /quit)
Press Ctrl+C while the model is generating to stop that answer."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive chat with the configured Qwen model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP,
    )
    parser.add_argument("--config", default=None, help="YAML config path (default: configs/model.yaml)")
    parser.add_argument("--system", default=None, help="optional system prompt for the whole session")
    parser.add_argument("--max-new-tokens", type=int, default=None, help="override generation.max_new_tokens")
    parser.add_argument("--temperature", type=float, default=None, help="override generation.temperature")
    parser.add_argument("--top-p", type=float, default=None, help="override generation.top_p")
    parser.add_argument("--top-k", type=int, default=None, help="override generation.top_k")
    parser.add_argument("--greedy", action="store_true", help="disable sampling (deterministic)")
    parser.add_argument("--thinking", action="store_true", help="enable Qwen3 thinking mode (slow on CPU)")
    parser.add_argument("--no-stream", action="store_true", help="print the full answer at once")
    parser.add_argument("--stats", action="store_true", help="show token counts and speed after each answer")
    parser.add_argument("--offline", action="store_true", help="fail instead of downloading if not cached")
    parser.add_argument("-v", "--verbose", action="store_true", help="show library logging")
    return parser.parse_args()


def apply_overrides(gen: GenerationConfig, args: argparse.Namespace) -> GenerationConfig:
    """CLI flags win over configs/model.yaml; unspecified flags keep the file's values."""
    if args.max_new_tokens is not None:
        gen.max_new_tokens = args.max_new_tokens
    if args.temperature is not None:
        gen.temperature = args.temperature
    if args.top_p is not None:
        gen.top_p = args.top_p
    if args.top_k is not None:
        gen.top_k = args.top_k
    if args.greedy:
        gen.do_sample = False
    if args.thinking:
        gen.enable_thinking = True
    return gen


def print_settings(settings: Settings, device: str, dtype: str, streaming: bool) -> None:
    gen = settings.generation
    print(f"  model:          {settings.model.id}")
    print(f"  device:         {device}  dtype: {dtype}")
    print(f"  max_new_tokens: {gen.max_new_tokens}")
    if gen.do_sample:
        print(f"  sampling:       temperature={gen.temperature} top_p={gen.top_p} top_k={gen.top_k}")
    else:
        print("  sampling:       off (greedy)")
    print(f"  thinking:       {gen.enable_thinking}")
    print(f"  streaming:      {streaming}")


def print_history(session: ChatSession) -> None:
    turns = session.transcript()
    if not turns:
        print("(no messages yet)")
        return
    for m in turns:
        label = "You" if m["role"] == "user" else "Qwen"
        print(f"{label}: {m['content']}\n")


def read_input() -> str | None:
    """Return the next line, or None on EOF."""
    try:
        return input("You: ")
    except EOFError:
        return None


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Model output may contain characters the Windows console codepage cannot encode.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    gen = apply_overrides(settings.generation, args)

    print(f"Loading {settings.model.id} ...", flush=True)
    try:
        t0 = time.perf_counter()
        tokenizer = load_tokenizer(settings.model, local_files_only=args.offline)
        model = load_model(settings.model, local_files_only=args.offline)
        load_seconds = time.perf_counter() - t0
    except ModelLoadError as exc:
        print(f"MODEL LOAD ERROR: {exc}", file=sys.stderr)
        return 1

    device_name = model.device.type.upper()
    if model.device.type == "cuda":
        device_name += f" ({environment_info().get('gpu_name')})"
    streaming = not args.no_stream
    streamer = None if args.no_stream else TextStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
    session = ChatSession(system_prompt=args.system)

    print(RULE)
    print("Qwen Interactive Chat")
    print(f"Model: {settings.model.id}")
    print(f"Device: {device_name}")
    print(f"Loaded in {load_seconds:.1f}s")
    print("Type /help for commands")
    print("Type /exit to quit")
    print(RULE)
    print()

    while True:
        try:
            line = read_input()
        except KeyboardInterrupt:
            print()
            line = None
        if line is None:
            break
        text = line.strip()
        if not text:
            continue

        if text.startswith("/"):
            cmd = text.split()[0].lower()
            if cmd in ("/exit", "/quit"):
                break
            if cmd == "/help":
                print(HELP)
            elif cmd == "/clear":
                session.clear()
                print("Conversation cleared.")
            elif cmd == "/history":
                print_history(session)
            elif cmd == "/settings":
                print_settings(settings, str(model.device), str(model.dtype), streaming)
            else:
                print(f"Unknown command {cmd}. Type /help for commands.")
            print()
            continue

        session.add_user(text)
        print("\nQwen: ", end="", flush=True)
        try:
            result = generate_chat(model, tokenizer, session.messages, gen, streamer=streamer)
        except KeyboardInterrupt:
            session.drop_last_user()
            print("\n[generation interrupted; that message was discarded]\n")
            continue
        except Exception as exc:  # keep the session alive on a failed turn
            session.drop_last_user()
            print(f"\nGENERATION ERROR: {type(exc).__name__}: {exc}\n", file=sys.stderr)
            continue

        thinking, answer = split_thinking(result.response)
        if args.no_stream:
            if thinking:
                print(f"[thinking]\n{thinking}\n[/thinking]")
            print(answer)
        elif not result.response:
            print("(empty response)")
        session.add_assistant(result.response)

        if args.stats:
            print(
                f"[{result.prompt_tokens} prompt tokens, {result.generated_tokens} new tokens, "
                f"{result.seconds:.1f}s, {result.tokens_per_second:.2f} tok/s, "
                f"{session.turns} turn(s) in context]"
            )
        print()

    print("Goodbye!")
    print(RULE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
