import streamlit as st
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
import os
from collections import Counter
import pandas as pd
from collections import defaultdict
import altair as alt
from duckduckgo_search import DDGS
import time
import random

# =====================
# Azure Search Settings
# =====================

SEARCH_SERVICE_NAME = os.getenv("SEARCH_SERVICE_NAME")
SEARCH_INDEX_NAME = os.getenv("SEARCH_INDEX_NAME")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY")

# Create Azure Search Client
endpoint = f"https://{SEARCH_SERVICE_NAME}.search.windows.net"
search_client = SearchClient(
    endpoint=endpoint,
    index_name=SEARCH_INDEX_NAME,
    credential=AzureKeyCredential(SEARCH_API_KEY)
)

# =====================
# Streamlit Page Config
# =====================
st.set_page_config(page_title="Kommunale Mødeudtræk", layout="wide")
st.title("🔍 Kommunale Mødeudtræk")

# Opret faner til navigation
tab1, tab2 = st.tabs(["Søg i kommunale møder", "Populære emner"])

# =====================
# Web Scraping Funktion
# =====================
def scrape_articles(query, count=3, max_retries=3):
    """
    Søger på DuckDuckGo efter relevante nyhedsartikler og håndterer rate limits.
    Implementerer en tilbageholdelsesstrategi for at undgå blokeringer.
    """
    results = []
    attempt = 0
    delay = 2  # Startforsinkelse i sekunder

    while attempt < max_retries:
        try:
            with DDGS() as ddgs:
                search_results = ddgs.text(query, max_results=count)

                for result in search_results:
                    title = result["title"]
                    url = result["href"]
                    snippet = result["body"]
                    results.append((title, url, snippet))

                break  # Afslutter loopet ved succes

        except Exception as e:
            print(f"⚠️ Fejl ved søgning: {e}")
            attempt += 1
            time.sleep(delay)
            delay *= 2

            if attempt == max_retries:
                print("❌ Maksimale antal forsøg nået. Returnerer tom liste.")
                return []

    time.sleep(random.uniform(1, 3))

    return results

# =====================
# Søgefunktionalitet
# =====================
def do_search(query_text="", filter_query=None, top=3, order_by=None):
    """
    Udfører en søgning med Azure Cognitive Search og returnerer dokumenter.
    """
    results = search_client.search(search_text=query_text, filter=filter_query, top=top, include_total_count=True, order_by=order_by or [])
    docs = [r for r in results]
    total_count = results.get_count()
    return docs, total_count

def show_results(docs, total_count=None):
    """
    Viser en liste over dokumenter i Streamlit UI samt relaterede artikler.
    """
    if total_count is not None:
        st.write(f"**Antal resultater:** {total_count}")

    for doc in docs:
        date_val = doc.get("date", "")

        # Konverter datoformat til YYYY-MM-DD
        if date_val:
            date_val = date_val.split("T")[0]

        municipality_val = doc.get("municipality", "")
        summary_val = doc.get("summary", "")
        decided = doc.get("decided_or_not", False)
        content_url = doc.get("content_url", "#")
        amount = doc.get("amount", "")
        search_sentences_val = doc.get("search_sentences", "")
        subject_title_val = doc.get("subject_title", "")
        description_val = doc.get("description", "")
        future_action_val = doc.get("future_action", "")
        tags_val = doc.get("tags", [])
        category_val = doc.get("category", "Ingen kategori")
        base_url = doc.get("site", "")

        # Hent relaterede artikler
        articles = scrape_articles(f"{subject_title_val} {municipality_val}")

        with st.expander(f"📌 {municipality_val} ({date_val})"):
            st.write(f"**Kommune:** {municipality_val}")
            st.write(f"**Resumé:** {summary_val}")
            st.write(f"**Emnetitel:** {subject_title_val}")
            st.write(f"**Emnebeskrivelse:** {description_val}")
            st.write(f"**Fremtidig handling:** {future_action_val}")
            if tags_val:
                if isinstance(tags_val, list):
                    st.write(f"**Tags for mødet generelt:** {', '.join(tags_val)}")
                else:
                    st.write(f"**Tags for mødet generelt:** {tags_val}")

            st.write(f"**Beslutning truffet:** {'Ja' if decided else 'Nej'}")
            if amount:
                st.write(f"**Bevilliget beløb:** {amount} DKK")

            st.write(f"**Søgesætninger til dokumentet:** {search_sentences_val}")

            if content_url != "#":
                st.markdown(f"[📄 **Se hele dokumentet**]({content_url})")

            # Vis relaterede artikler
            st.markdown("#### 🔗 Relaterede artikler")
            valid_articles = [(title, link) for title, link, _ in articles if title.strip() and link.strip()]

            if valid_articles:
                for article_title, article_link in valid_articles:
                    st.markdown(f"- **[{article_title}]({article_link})**")
            else:
                st.write("Ingen relaterede artikler fundet.")

# =====================
# Hovedsøgefunktion
# =====================
with tab1:
    with st.expander("### ℹ️ Sådan bruger du appen (Klik for at se mere)"):
        st.markdown("""
            Denne **Kommunale Mødeudtræk** app gør det nemt at **søge og udforske kommunale mødereferater** fra forskellige danske kommuner.

            ### 🔍 **Sådan bruger du appen:**
            1️⃣ **Søg i kommunale møder**  
               - Indtast et søgeord (f.eks. *"bolig"*, *"budget"*, *"miljø"*).  
               - Filtrér på **kommune** og **dato** efter behov.  
               - Klik på **"🔎 Søg"** for at finde relevante møder.  

            2️⃣ **Gennemse resultaterne**  
               - Klik på **📌** for at udvide og se detaljer om et møde.  
               - Se **resumé, emne, beslutninger og fremtidige handlinger**.  
               - Klik på **"Se hele dokumentet"** for at læse originalreferatet.  

            3️⃣ **Relaterede nyhedsartikler**  
               - Appen søger automatisk efter **relevante artikler** baseret på emnet.  
               - Klik på de viste links for at læse mere.  

            4️⃣ **Populære emner**  
               - Under fanen **"Populære emner"** kan du se **hvilke emner der diskuteres mest** i kommunerne.  

            📌 **Formål:** Øget gennemsigtighed i kommunale beslutninger og let adgang til information om lokalpolitik.
        """)

    st.subheader("Søg i kommunale møder")

    query = st.text_input("Søg efter et emne (f.eks. 'bolig', 'budget', 'miljø'):", "")
    municipalities = ["Alle", "Slagelse", "Faxe", "Gladsaxe", "Herlev", "Hillerød", "Holbæk", "Hørsholm", "Næstved", "Odsherred", "Stevns", "Anden kommune"]
    municipality_filter = st.selectbox("Filtrér efter kommune:", municipalities)

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Startdato", value=None)
    with col2:
        end_date = st.date_input("Slutdato", value=None)

    filter_clauses = []
    if municipality_filter != "Alle":
        filter_clauses.append(f"municipality eq '{municipality_filter}'")

    if start_date and end_date:
        filter_clauses.append(f"date ge {start_date.isoformat()}T00:00:00Z and date le {end_date.isoformat()}T23:59:59Z")
    elif start_date:
        filter_clauses.append(f"date ge {start_date.isoformat()}T00:00:00Z")
    elif end_date:
        filter_clauses.append(f"date le {end_date.isoformat()}T23:59:59Z")

    filter_query = " and ".join(filter_clauses) if filter_clauses else None

    if st.button("🔎 Søg"):
        with st.spinner("Søger..."):
            try:
                docs, total_count = do_search(query_text=query, filter_query=filter_query, top=20)
                show_results(docs, total_count)
            except Exception as e:
                st.error(f"Der opstod en fejl: {e}")

    st.markdown("---")

# =====================
# Sektion for Populære Emner
# =====================
with tab2:
    st.subheader("Populære Emner")

    # ------------------
    # 1) Fetch Documents
    # ------------------
    def fetch_all_docs(search_client, top=1000):
        """
        Fetch up to 'top' documents from the Azure Search index.
        Increase 'top' or implement continuation tokens if you have more than 1000 docs.
        """
        docs_iter = search_client.search(search_text="*", top=top)
        return list(docs_iter)


    # -------------------------
    # 2) Show Popular Categories
    # -------------------------
    def show_popular_categories(search_client):
        """
        Overall category frequency across all municipalities (no filter).
        """
        st.header("Populære Kategorier (Alle Kommuner)")
        docs = fetch_all_docs(search_client, top=1000)

        # Aggregate category frequency
        cat_counter = Counter(doc.get("category", "") for doc in docs)
        data = [(cat, cat_counter[cat]) for cat in cat_counter]
        df = pd.DataFrame(data, columns=["category", "count"]).sort_values("count", ascending=False)

        # Display table
        st.dataframe(df)

        # Display bar chart
        st.bar_chart(df.set_index("category"))


    # --------------------------------------------
    # 3) Show Categories Across Municipalities (Combined Chart)
    # --------------------------------------------
    def show_categories_by_municipality(search_client):
        """
        Shows a single bar chart comparing all municipalities vs. category counts.
        """
        st.header("Kategorier efter Kommuner (Samlet Overblik)")
        docs = fetch_all_docs(search_client, top=1000)

        # Build a nested dictionary: { municipality -> { category -> count } }
        grouped = defaultdict(lambda: defaultdict(int))
        for doc in docs:
            muni = doc.get("municipality", "Unknown")
            cat = doc.get("category", "Uncategorized")
            grouped[muni][cat] += 1

        # Flatten into rows
        rows = []
        for muni, cat_dict in grouped.items():
            for cat, cnt in cat_dict.items():
                rows.append({"municipality": muni, "category": cat, "count": cnt})

        if not rows:
            st.write("No data found.")
            return

        df = pd.DataFrame(rows)

        # Create an Altair bar chart
        chart = alt.Chart(df).mark_bar().encode(
            x=alt.X("category:N", sort='-y'),
            y=alt.Y("count:Q"),
            color="municipality:N",
            tooltip=["municipality:N", "category:N", "count:Q"]
        ).properties(
            width=600,
            height=400
        )
        st.altair_chart(chart, use_container_width=True)


    # -----------------------------------------------------
    # 4) Show Categories for a Single Municipality (Filter)
    # -----------------------------------------------------
    def show_categories_for_single_municipality(search_client):
        """
        Let user pick one municipality and see categories + counts just for that municipality.
        """
        st.header("Kategorier for Udvalgte Kommuner")
        docs = fetch_all_docs(search_client, top=1000)

        # Gather unique municipality names from docs
        municipalities = set(doc.get("municipality", "Unknown") for doc in docs)
        municipalities = sorted(municipalities)
        municipalities.insert(0, "All")  # Option to view all municipalities combined

        selected_muni = st.selectbox("Vælg en kommune:", municipalities)

        # Filter docs if user doesn't pick "All"
        if selected_muni != "All":
            docs = [d for d in docs if d.get("municipality", "Unknown") == selected_muni]

        # Tally up category counts
        cat_counter = Counter(d.get("category", "Uncategorized") for d in docs)
        data = [(cat, cat_counter[cat]) for cat in cat_counter]
        df = pd.DataFrame(data, columns=["category", "count"]).sort_values("count", ascending=False)

        if df.empty:
            st.write("No categories found for this selection.")
            return

        # Show table
        st.dataframe(df)

        # Bar Chart for this municipality
        chart = alt.Chart(df).mark_bar().encode(
            x=alt.X("count:Q", title="Count"),
            y=alt.Y("category:N", sort='-x', title="Category"),
            tooltip=["category", "count"]
        ).properties(
            width=600,
            height=400
        )
        st.altair_chart(chart, use_container_width=True)


    # ---------------------------
    # 5) Main "Popular Topics" App
    # ---------------------------
    def popular_topics_app(search_client):
        """
        Wraps all your 'popular topics' functionality into a single function.
        """
        st.title("Popular Topics Overview")

        # 1) Show overall categories
        show_popular_categories(search_client)
        st.write("---")

        # 2) Show combined categories by all municipalities
        show_categories_by_municipality(search_client)
        st.write("---")

        # 3) Show categories for a single municipality (filtered)
        show_categories_for_single_municipality(search_client)

    popular_topics_app(search_client)

    #st.write("This section is currently under development.")