from db import initialize_database
from agent import chat


def main():
    initialize_database()
    print("\nSmartBook AI - Cinema Demo")
    print("Try: 'list movies', 'tell me about Inception', or 'what is your cancellation policy?' ")
    print("Type 'exit' to quit. Demo identity: demo-customer (customer role).\n")
    while True:
        try:
            message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        if message.lower() in {"exit", "quit"}:
            print("Goodbye!")
            break
        if not message:
            continue
        try:
            print("Agent:", chat(message))
        except Exception as exc:
            print("Agent: The request could not be completed. Check your model configuration and try again.")
            print(f"Debug detail: {type(exc).__name__}: {exc}")

if __name__ == "__main__":
    main()
