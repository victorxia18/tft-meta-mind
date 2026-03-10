"""RAG chatbot using the Google Gemini API.

Retrieves relevant TFT knowledge from the vector store and uses
Gemini to generate informed, context-aware responses.

Usage:
    python -m chatbot.app
"""

import logging
import re

from google import genai

from rag.vector_store import TFTVectorStore

logger = logging.getLogger(__name__)

# Keywords that signal a unit-specific question
UNIT_KEYWORDS = re.compile(
    r"\b(unit|champion|champ|items?\s+on|build|itemize|"
    r"3[- ]?star|best items?|tier list|s[- ]?tier|a[- ]?tier)\b",
    re.IGNORECASE,
)

# Keywords that signal a comp/meta question
COMP_KEYWORDS = re.compile(
    r"\b(comp|composition|team|meta|strongest|best comp|"
    r"what.*(play|run|climb)|top 4|bot 4|consistent)\b",
    re.IGNORECASE,
)


class TFTChatbot:
    """RAG-powered TFT chatbot using Google Gemini API."""

    def __init__(self, gemini_api_key: str, vector_store: TFTVectorStore):
        self.client = genai.Client(api_key=gemini_api_key)
        self.vector_store = vector_store

    def build_system_prompt(self) -> str:
        return (
            "You are TFT Meta Mind, an expert Teamfight Tactics analyst and coach. "
            "You help players understand the current meta, choose comps, pick items, "
            "and improve their gameplay.\n\n"
            "When answering questions:\n"
            "1. Base your answers on the retrieved context (comp stats, unit data). "
            "Cite specific stats: average placement, top 4 rate, win rate, best items.\n"
            "2. If the context doesn't contain enough info, say so honestly.\n"
            "3. Give actionable advice for climbing ranked — not just data dumps. "
            "When recommending comps, mention core units, key items, and expected placement.\n"
            "4. When discussing units, mention their best items and 3-star potential "
            "if that data exists in the context.\n"
            "5. Use TFT language: 'top 4' = good result, 'first' = win, 'bot 4' = bad result.\n"
            "6. Do NOT mention augments — we do not have augment data.\n"
            "7. Keep answers concise but informative. Players want quick, actionable info."
        )

    def _retrieve(self, question: str, n_results: int = 5) -> list[dict]:
        """Retrieve relevant chunks with smart filtering based on question type."""
        results = []

        # Check if the question is unit-specific or comp-specific
        is_unit_q = bool(UNIT_KEYWORDS.search(question))
        is_comp_q = bool(COMP_KEYWORDS.search(question))

        if is_unit_q and not is_comp_q:
            # Primarily a unit question — get unit_analysis chunks + some general
            unit_results = self.vector_store.query(
                question, n_results=3, where={"type": "unit_analysis"}
            )
            general_results = self.vector_store.query(question, n_results=2)
            results = unit_results + general_results
        elif is_comp_q and not is_unit_q:
            # Primarily a comp/meta question — get meta_snapshot chunks + some general
            comp_results = self.vector_store.query(
                question, n_results=3, where={"type": "meta_snapshot"}
            )
            general_results = self.vector_store.query(question, n_results=2)
            results = comp_results + general_results
        else:
            # Ambiguous or general — let embedding similarity decide
            results = self.vector_store.query(question, n_results=n_results)

        # Deduplicate by chunk text
        seen = set()
        unique = []
        for r in results:
            if r["text"] not in seen:
                seen.add(r["text"])
                unique.append(r)

        return unique[:n_results]

    def ask(
        self,
        question: str,
        n_context_chunks: int = 5,
        chat_history: list[dict] | None = None,
    ) -> str:
        """Answer a TFT question using RAG.

        Args:
            question: The user's question.
            n_context_chunks: How many context chunks to retrieve.
            chat_history: Optional list of {"role": str, "content": str} dicts
                          for multi-turn conversation.

        Returns:
            The chatbot's response text.
        """
        chunks = self._retrieve(question, n_results=n_context_chunks)

        if not chunks:
            context_block = "(No data available in the knowledge base yet.)"
        else:
            context_parts = []
            for r in chunks:
                source = r["metadata"].get("source", "unknown")
                date = r["metadata"].get("date", "unknown")
                doc_type = r["metadata"].get("type", "unknown")
                context_parts.append(
                    f"[Source: {source} | Type: {doc_type} | Date: {date}]\n{r['text']}"
                )
            context_block = "\n\n---\n\n".join(context_parts)

        user_message = (
            "Here is relevant TFT data and context to help answer the question:\n\n"
            f"<context>\n{context_block}\n</context>\n\n"
            f"Player's Question: {question}\n\n"
            "Please provide a helpful, specific answer based on the context above."
        )

        # Build contents list: chat history + current message
        # Gemini uses "user" and "model" roles
        contents = []
        if chat_history:
            for msg in chat_history:
                role = "model" if msg["role"] == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        contents.append({"role": "user", "parts": [{"text": user_message}]})

        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config={
                "system_instruction": self.build_system_prompt(),
                "max_output_tokens": 1024,
            },
        )

        return response.text


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from dotenv import load_dotenv
    import os

    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in .env file.")
        raise SystemExit(1)

    print("Initializing vector store...")
    store = TFTVectorStore()
    stats = store.get_stats()
    print(f"Knowledge base: {stats['total_chunks']} chunks")

    if stats["total_chunks"] == 0:
        print("No data in vector store. Run the ingestion pipeline first.")
        raise SystemExit(1)

    print("Initializing chatbot...")
    bot = TFTChatbot(gemini_api_key=api_key, vector_store=store)

    test_questions = [
        "What are the strongest comps right now?",
        "What items should I build on Fizz?",
        "I keep going bot 4, what comps are most consistent for top 4?",
    ]

    for q in test_questions:
        print(f"\n{'=' * 60}")
        print(f"Q: {q}")
        print("-" * 60)
        answer = bot.ask(q)
        print(answer)
