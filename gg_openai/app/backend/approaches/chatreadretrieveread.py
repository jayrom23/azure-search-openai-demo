import openai
from azure.search.documents import SearchClient
from azure.search.documents.models import QueryType
from approaches.approach import Approach
from text import nonewlines

# Simple retrieve-then-read implementation, using the Cognitive Search and OpenAI APIs directly. It first retrieves
# top documents from search, then constructs a prompt with them, and then uses OpenAI to generate an completion 
# (answer) with that prompt.
class ChatReadRetrieveReadApproach(Approach):
    prompt_prefix = """<|im_start|>system
Als Assistent und Nachhaltigkeitsanalyst unterstützt du die Mitarbeiter der Gadget abc Entertainment Group AG bei Fragen zur Nachhaltigkeitsstrategie, Maßnahmen und Überwachung in ihren Unternehmensdokumenten. 
Als Nachhaltigkeitsanalyst, der sich auf die Live-Musikindustrie in der Schweiz spezialisiert hat ist es dein Ziel es, die durch Konzerte und Festivals enstehenden CO2-Emissionen so weit wie möglich zu reduzieren, die Besucher für Umweltthemen zu sensibilisieren, um zukünftige Einsparungen durch nachhaltigeres Verhalten zu erzielen und sicherzustellen, dass alle Akteure, die von den Nachhaltigkeitsmassnahmen betroffen sind, maximal kooperationsbereit sind. 
Gib kurze Antworten. Antworte auf der Grundlage der unten aufgelisteten Informationsquellen und deinem Wissen über Nachhaltigkeitsstrategien. Wenn nicht genügend Informationen vorhanden sind, sage bitte, dass du es nicht weißt. Generiere keine Antworten, die die unten genannten Quellen nicht nutzen. Wenn es hilfreich wäre, eine klärende Frage an den Benutzer zu stellen, stelle bitte die Frage.
Gib Tabelleninformationen als HTML-Tabelle zurück. Verwende nicht das Markdown-Format. Jede Quelle hat einen Namen, gefolgt von einem Doppelpunkt und den tatsächlichen Informationen. Gib bei jeder Tatsache, die du in der Antwort verwendest, den Namen der Quelle an. Verwende eckige Klammern, um auf die Quelle zu verweisen, z.B. [info1.txt]. Kombiniere keine Quellen, liste jede Quelle separat auf, z.B. [info1.txt][info2.pdf].
{follow_up_questions_prompt}
{injected_prompt}
Quellen:
{sources}
<|im_end|>
{chat_history}
"""

    follow_up_questions_prompt_content = """Generiere drei sehr kurze Folgefragen, die der Benutzer wahrscheinlich als nächstes zu den Dokumenten und der Nachhaltigkeitsstrategie, Massnahmen oder der Datenauswertung stellen würde. 
    Verwende doppelte spitze Klammern, um auf die Fragen zu verweisen, z.B. <<Kannst du mir dafür genauere Anweisungen geben??>> oder <<Kannst du mir das genauer erklären??>>. 
    Wiederhole keine bereits gestellten Fragen. Generiere nur Fragen und keinen Text vor oder nach den Fragen, wie zum Beispiel "Nächste Fragen"."""

    query_prompt_template = """Unten findest du den bisherigen Gesprächsverlauf und eine neue Frage, die vom Benutzer gestellt wurde und die durch das Suchen in einer Wissensdatenbank über Nachhaltigkeitsstrategien und Klimabilanzierungsdaten beantwortet werden muss.
    Generiere eine Suchanfrage basierend auf dem Gespräch und der neuen Frage. Füge in den Suchbegriffen der Suchanfrage keine Dateinamen für zitierte Quellen und Dokumente ein, z.B. info.txt oder doc.pdf. 
    Füge in den Suchbegriffen der Suchanfrage keinen Text innerhalb von [] oder <<>> ein. 

Chatverlauf: {chat_history}

Frage: {question}

Suchanfrage:
"""

    def __init__(self, search_client: SearchClient, chatgpt_deployment: str, gpt_deployment: str, sourcepage_field: str, content_field: str):
        self.search_client = search_client
        self.chatgpt_deployment = chatgpt_deployment
        self.gpt_deployment = gpt_deployment
        self.sourcepage_field = sourcepage_field
        self.content_field = content_field

    def run(self, history: list[dict], overrides: dict) -> any:
        use_semantic_captions = True if overrides.get("semantic_captions") else False
        top = overrides.get("top") or 3
        exclude_category = overrides.get("exclude_category") or None
        filter = "category ne '{}'".format(exclude_category.replace("'", "''")) if exclude_category else None

        # STEP 1: Generate an optimized keyword search query based on the chat history and the last question
        prompt = self.query_prompt_template.format(chat_history=self.get_chat_history_as_text(history, include_last_turn=False), question=history[-1]["user"])
        completion = openai.Completion.create(
            engine=self.gpt_deployment, 
            prompt=prompt, 
            temperature=0.0, 
            max_tokens=32, 
            n=1, 
            stop=["\n"])
        q = completion.choices[0].text

        # STEP 2: Retrieve relevant documents from the search index with the GPT optimized query
        if overrides.get("semantic_ranker"):
            r = self.search_client.search(q, 
                                          filter=filter,
                                          query_type=QueryType.SEMANTIC, 
                                          query_language="en-us", 
                                          query_speller="lexicon", 
                                          semantic_configuration_name="default", 
                                          top=top, 
                                          query_caption="extractive|highlight-false" if use_semantic_captions else None)
        else:
            r = self.search_client.search(q, filter=filter, top=top)
        if use_semantic_captions:
            results = [doc[self.sourcepage_field] + ": " + nonewlines(" . ".join([c.text for c in doc['@search.captions']])) for doc in r]
        else:
            results = [doc[self.sourcepage_field] + ": " + nonewlines(doc[self.content_field]) for doc in r]
        content = "\n".join(results)

        follow_up_questions_prompt = self.follow_up_questions_prompt_content if overrides.get("suggest_followup_questions") else ""
        
        # Allow client to replace the entire prompt, or to inject into the exiting prompt using >>>
        prompt_override = overrides.get("prompt_template")
        if prompt_override is None:
            prompt = self.prompt_prefix.format(injected_prompt="", sources=content, chat_history=self.get_chat_history_as_text(history), follow_up_questions_prompt=follow_up_questions_prompt)
        elif prompt_override.startswith(">>>"):
            prompt = self.prompt_prefix.format(injected_prompt=prompt_override[3:] + "\n", sources=content, chat_history=self.get_chat_history_as_text(history), follow_up_questions_prompt=follow_up_questions_prompt)
        else:
            prompt = prompt_override.format(sources=content, chat_history=self.get_chat_history_as_text(history), follow_up_questions_prompt=follow_up_questions_prompt)

        # STEP 3: Generate a contextual and content specific answer using the search results and chat history
        completion = openai.Completion.create(
            engine=self.chatgpt_deployment, 
            prompt=prompt, 
            temperature=overrides.get("temperature") or 0.7, 
            max_tokens=1024, 
            n=1, 
            stop=["<|im_end|>", "<|im_start|>"])

        return {"data_points": results, "answer": completion.choices[0].text, "thoughts": f"Searched for:<br>{q}<br><br>Prompt:<br>" + prompt.replace('\n', '<br>')}
    
    def get_chat_history_as_text(self, history, include_last_turn=True, approx_max_tokens=1000) -> str:
        history_text = ""
        for h in reversed(history if include_last_turn else history[:-1]):
            history_text = """<|im_start|>user""" +"\n" + h["user"] + "\n" + """<|im_end|>""" + "\n" + """<|im_start|>assistant""" + "\n" + (h.get("bot") + """<|im_end|>""" if h.get("bot") else "") + "\n" + history_text
            if len(history_text) > approx_max_tokens*4:
                break    
        return history_text