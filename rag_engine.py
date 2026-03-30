"""
RAG Engine Module
Multi-provider LangChain RAG with streaming support.
Supports: Groq, OpenAI, Gemini, Anthropic, Mistral, DeepSeek.
"""

import os
import json
from dotenv import load_dotenv

from langchain.chains import create_history_aware_retriever, create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


load_dotenv()

SYSTEM_PROMPT = """You are an **AI Academic Assistant** — a professional tutor.

## RULES
- Be **concise**. Give direct, to-the-point answers.
- Do NOT over-explain. Keep responses short unless the user asks for detail.
- Use Markdown: headings, bold key terms, bullet points.
- Use context from retrieved documents first; fall back to your knowledge.
- Never mention "based on the documents" or "as per context".
- No filler, no meta-commentary, no redundant summaries.
- Use LaTeX for math ($E=mc^2$), code blocks for code.
"""


def _create_llm(provider: str, model_name: str, api_key: str):
    """Factory function to create the correct LangChain LLM based on provider."""
    common_kwargs = {
        "temperature": 0.3,
        "max_tokens": 1024,
        "streaming": True,
    }

    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(api_key=api_key, model_name=model_name, **common_kwargs)

    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(api_key=api_key, model=model_name, **common_kwargs)

    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            google_api_key=api_key,
            model=model_name,
            temperature=common_kwargs["temperature"],
            max_output_tokens=common_kwargs["max_tokens"],
            streaming=True,
        )

    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            anthropic_api_key=api_key,
            model_name=model_name,
            temperature=common_kwargs["temperature"],
            max_tokens=common_kwargs["max_tokens"],
            streaming=True,
        )

    elif provider == "mistral":
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(
            api_key=api_key,
            model=model_name,
            temperature=common_kwargs["temperature"],
            max_tokens=common_kwargs["max_tokens"],
            streaming=True,
        )

    elif provider == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            api_key=api_key,
            model=model_name,
            base_url="https://api.deepseek.com/v1",
            **common_kwargs,
        )

    elif provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            api_key=api_key,
            model=model_name,
            base_url="https://openrouter.ai/api/v1",
            **common_kwargs,
        )

    elif provider == "perplexity":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            api_key=api_key,
            model=model_name,
            base_url="https://api.perplexity.ai",
            **common_kwargs,
        )

    elif provider == "together":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            api_key=api_key,
            model=model_name,
            base_url="https://api.together.xyz/v1",
            **common_kwargs,
        )

    elif provider == "xai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            api_key=api_key,
            model=model_name,
            base_url="https://api.x.ai/v1",
            **common_kwargs,
        )

    elif provider == "nvidia":
        from langchain_openai import ChatOpenAI
        key_to_use = api_key if api_key else "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"
        return ChatOpenAI(
            api_key=key_to_use,
            model=model_name,
            base_url="https://integrate.api.nvidia.com/v1",
            model_kwargs={"reasoning_effort": "none"},
            **common_kwargs,
        )

    else:
        raise ValueError(f"Unsupported AI provider: {provider}")


class RAGEngine:
    """
    Multi-provider LangChain RAG engine with streaming.
    """

    def __init__(self, vector_store, provider="groq", model_name=None, api_key=None):
        self.vector_store = vector_store
        self.llm = None
        self.provider = provider
        self.model_name = model_name or "llama-3.3-70b-versatile"
        self.history = []
        self._chain = None

        if api_key or provider == "nvidia":
            self._init_llm(api_key)

    def _init_llm(self, api_key: str):
        """Initialize the LLM for the configured provider."""
        try:
            self.llm = _create_llm(self.provider, self.model_name, api_key)
            self._chain = None
        except Exception as e:
            print(f"[RAG Engine] Failed to initialize LLM for {self.provider}/{self.model_name}: {e}")
            self.llm = None

    def _get_chain(self):
        if self._chain is not None:
            return self._chain

        if self.vector_store is None or self.llm is None:
            return None

        retriever = self.vector_store.as_retriever(top_k=5)

        contextualize_q_system_prompt = (
            "Given a chat history and the latest user question "
            "which might reference context in the chat history, "
            "formulate a standalone question which can be understood "
            "without the chat history. Do NOT answer the question, "
            "just reformulate it if needed and otherwise return it as is."
        )
        contextualize_q_prompt = ChatPromptTemplate.from_messages([
            ("system", contextualize_q_system_prompt),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ])
        history_aware_retriever = create_history_aware_retriever(
            self.llm, retriever, contextualize_q_prompt
        )

        qa_system_prompt = (
            "You are a Premium AI Academic Assistant. Your task is to provide expert-level answers using retrieved context.\n\n"
            "CRITICAL PRIORITY: You MUST analyze the **Retrieved Academic Context** provided below first. If it contains relevant information, "
            "it takes absolute precedence. Use your internal knowledge only to supplement or if the context is entirely irrelevant.\n\n"
            f"{SYSTEM_PROMPT}\n\n"
            "## Retrieved Academic Context\n"
            "{context}"
        )
        qa_prompt = ChatPromptTemplate.from_messages([
            ("system", qa_system_prompt),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ])

        question_answer_chain = create_stuff_documents_chain(self.llm, qa_prompt)
        self._chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)
        return self._chain

    def set_api_key(self, api_key: str):
        if api_key or self.provider == "nvidia":
            self._init_llm(api_key)
        else:
            self.llm = None
            self._chain = None

    def has_api_key(self) -> bool:
        return self.llm is not None

    def detect_intent(self, query: str) -> str:
        query_lower = query.lower()
        if any(kw in query_lower for kw in ['difference', 'compare', 'vs', 'versus', 'distinguish', 'differentiate']):
            return 'comparison'
        elif any(kw in query_lower for kw in ['roadmap', 'study plan', 'schedule', 'prepare', 'preparation', 'week-wise', 'plan for']):
            return 'roadmap'
        elif any(kw in query_lower for kw in ['solve', 'answer', 'find', 'calculate', 'compute', 'derive', 'prove', 'write a program', 'write code']):
            return 'question_solving'
        elif any(kw in query_lower for kw in ['summarize', 'summary', 'brief', 'short notes', 'revision']):
            return 'summary'
        return 'topic_explanation'

    def stream_generate_response(self, query: str):
        if not self.llm:
            yield f"data: {json.dumps({'error': f'LLM not initialized. Check your API key for {self.provider}.'})}\n\n"
            return

        intent = self.detect_intent(query)
        chain = self._get_chain()

        try:
            full_answer = ""
            sources = []

            if chain is not None:
                for chunk in chain.stream({"input": query, "chat_history": self.history}):
                    if "answer" in chunk:
                        token = chunk["answer"]
                        full_answer += token
                        yield f"data: {json.dumps({'token': token})}\n\n"

                    if "context" in chunk:
                        seen = set()
                        for doc in chunk["context"]:
                            src = doc.metadata.get('source', '')
                            page = doc.metadata.get('page')
                            if not src or src == 'Unknown':
                                continue
                            key = f"{src}_{page}" if page is not None else src
                            if key not in seen:
                                entry = {'name': src}
                                if page is not None:
                                    entry['page'] = page
                                sources.append(entry)
                                seen.add(key)

                yield f"data: {json.dumps({'intent': intent, 'sources': sources, 'done': True})}\n\n"

                self.history.append(HumanMessage(content=query))
                self.history.append(AIMessage(content=full_answer))
                if len(self.history) > 12:
                    self.history = self.history[-12:]

            else:
                messages = [
                    SystemMessage(content=SYSTEM_PROMPT),
                    *self.history,
                    HumanMessage(content=query)
                ]

                for chunk in self.llm.stream(messages):
                    token = chunk.content
                    full_answer += token
                    yield f"data: {json.dumps({'token': token})}\n\n"

                yield f"data: {json.dumps({'intent': intent, 'sources': [], 'done': True})}\n\n"

                self.history.append(HumanMessage(content=query))
                self.history.append(AIMessage(content=full_answer))
                if len(self.history) > 12:
                    self.history = self.history[-12:]

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    def clear_history(self):
        self.history = []
        self._chain = None

