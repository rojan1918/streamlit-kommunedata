import streamlit as st
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from collections import Counter, defaultdict
import pandas as pd
import altair as alt
#from duckduckgo_search import DDGS
import time
import random
#from datetime import datetime

# =====================
# Database Settings
# =====================
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")

def get_db_connection():
    """Create database connection"""
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        cursor_factory=RealDictCursor
    )

# =====================
# Web Scraping Funktion
# =====================
# def scrape_articles(query, count=3, max_retries=3):
#     """
#     Søger på DuckDuckGo efter relevante nyhedsartikler og håndterer rate limits.
#     Implementerer en tilbageholdelsesstrategi for at undgå blokeringer.
#     """
#     results = []
#     attempt = 0
#     delay = 2  # Startforsinkelse i sekunder
#
#     while attempt < max_retries:
#         try:
#             with DDGS() as ddgs:
#                 search_results = ddgs.text(query, max_results=count)
#
#                 for result in search_results:
#                     title = result["title"]
#                     url = result["href"]
#                     snippet = result["body"]
#                     results.append((title, url, snippet))
#
#                 break  # Afslutter loopet ved succes
#
#         except Exception as e:
#             print(f"⚠️ Fejl ved søgning: {e}")
#             attempt += 1
#             time.sleep(delay)
#             delay *= 2
#
#             if attempt == max_retries:
#                 print("❌ Maksimale antal forsøg nået. Returnerer tom liste.")
#                 return []
#
#     time.sleep(random.uniform(1, 3))
#
#     return results

# =====================
# Søgefunktionalitet
# =====================
def refresh_materialized_view():
    """Refresh the materialized view"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("REFRESH MATERIALIZED VIEW sourceview.foraisearch_with_search")
        conn.commit()
    except Exception as e:
        st.error(f"Error refreshing materialized view: {e}")
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()


def do_search(query_text="", municipality=None, start_date=None, end_date=None, limit=20):
    """
    Perform full-text search using PostgreSQL
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Build the query
        query = """
                    SELECT 
                        t.id, t.municipality, t.date, t.participants, t.guests, t.title, 
                        t.summary, t.tags, t.content_url, t.category, t.search_sentences,
                        t.decided_or_not, t.future_action, t.description, t.subject_title, t.amount,
                        COALESCE(ts_rank_score, 0) as ts_rank_score,
                        COALESCE(similarity_score, 0) as similarity_score
                    FROM (
                        SELECT 
                            *,
                            ts_rank(search_vector, plainto_tsquery('danish', %s)) as ts_rank_score,
                            similarity(
                                (((((((((COALESCE(municipality, '')::text || ' ') || 
                                COALESCE(title, '')::text) || ' ') || 
                                COALESCE(category, '')::text) || ' ') || 
                                COALESCE(description, '')::text) || ' ') || 
                                COALESCE(future_action, '')::text) || ' ') || 
                                COALESCE(subject_title, '')::text,
                                %s
                            ) as similarity_score
                        FROM sourceview.foraisearch_with_search
                    ) t
                    WHERE """

        params = [query_text, query_text]

        # Add wildcard search for even better matches
        wildcard_query = " | ".join([f"{word}:*" for word in query_text.split()])

        # Add conditions - both exact matches and similarity
        where_conditions = [
            "t.search_vector @@ plainto_tsquery('danish', %s)",
            "t.search_vector @@ to_tsquery('danish', %s)",
            "t.similarity_score > 0.05"  # Adjust threshold as needed
        ]

        query += " OR ".join(where_conditions)
        params.extend([query_text, wildcard_query])

        # Add filters
        if municipality and municipality != "Alle":
            query += " AND municipality = %s"
            params.append(municipality)

        if start_date:
            query += " AND date::date >= %s"
            params.append(start_date)

        if end_date:
            query += " AND date::date <= %s"
            params.append(end_date)

            # Add ordering and limit
            query += """
            ORDER BY ((ts_rank(search_vector, plainto_tsquery('danish', %s))) + (similarity(
                                (((((((((COALESCE(municipality, '')::text || ' ') || 
                                COALESCE(title, '')::text) || ' ') || 
                                COALESCE(category, '')::text) || ' ') || 
                                COALESCE(description, '')::text) || ' ') || 
                                COALESCE(future_action, '')::text) || ' ') || 
                                COALESCE(subject_title, '')::text,
                                %s
                            )) * 0.8) DESC LIMIT %s
            """
            params.append(limit)

        # Execute search
        cur.execute(query, params)
        results = cur.fetchall()

        # Count query for total matches
        count_query = """
                    SELECT COUNT(*) 
                    FROM (
                        SELECT 
                            *,
                            ts_rank(search_vector, plainto_tsquery('danish', %s)) as ts_rank_score,
                            similarity(
                                (((((((((COALESCE(municipality, '')::text || ' ') || 
                                COALESCE(title, '')::text) || ' ') || 
                                COALESCE(category, '')::text) || ' ') || 
                                COALESCE(description, '')::text) || ' ') || 
                                COALESCE(future_action, '')::text) || ' ') || 
                                COALESCE(subject_title, '')::text,
                                %s
                            ) as similarity_score
                        FROM sourceview.foraisearch_with_search
                    ) t
                    WHERE """

        count_params = [query_text, query_text]

        count_query += " OR ".join(where_conditions)
        count_params.extend([query_text, wildcard_query])

        if municipality and municipality != "Alle":
            count_query += " AND municipality = %s"
            count_params.append(municipality)

        if start_date:
            count_query += " AND date::date >= %s"
            count_params.append(start_date)

        if end_date:
            count_query += " AND date::date <= %s"
            count_params.append(end_date)

        cur.execute(count_query, count_params)
        total_count = cur.fetchone()['count']

        return results, total_count

    except Exception as e:
        st.error(f"Search error: {e}")
        return [], 0
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()


def show_results(docs, total_count=None):
    """
    Viser en liste over dokumenter i Streamlit UI samt relaterede artikler.
    """
    if total_count is not None:
        st.write(f"**Antal resultater:** {total_count}")

    for doc in docs:
        date_val = doc.get("date", "")

        # Konverter datoformat til YYYY-MM-DD
        # With this:
        if date_val:
            if isinstance(date_val, str):
                date_val = date_val.split("T")[0]
            else:
                date_val = date_val.strftime("%Y-%m-%d")

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

        # # Hent relaterede artikler
        # articles = scrape_articles(f"{subject_title_val} {municipality_val}")

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

            # # Vis relaterede artikler
            # st.markdown("#### 🔗 Relaterede artikler")
            # valid_articles = [(title, link) for title, link, _ in articles if title.strip() and link.strip()]
            #
            # if valid_articles:
            #     for article_title, article_link in valid_articles:
            #         st.markdown(f"- **[{article_title}]({article_link})**")
            # else:
            #     st.write("Ingen relaterede artikler fundet.")


def add_custom_css():
    # Create custom CSS for input field styling
    custom_css = """
        <style>
            /* Target the Streamlit text input, selectbox, and date input fields */
            .stTextInput input, .stSelectbox select, .stDateInput input {
                border: 2px solid #4e89ae !important;  /* Add a blue border */
                border-radius: 5px !important;         /* Rounded corners */
                padding: 10px !important;              /* More padding for better visibility */
                box-shadow: 0 0 5px rgba(78, 137, 174, 0.2) !important;  /* Subtle shadow */
            }

            /* Hover effect for better user experience */
            .stTextInput input:hover, .stSelectbox select:hover, .stDateInput input:hover {
                border-color: #2c699a !important;      /* Darker blue on hover */
                box-shadow: 0 0 8px rgba(78, 137, 174, 0.4) !important;  /* Enhanced shadow */
            }
        </style>
    """
    # Inject the CSS into the Streamlit app
    st.markdown(custom_css, unsafe_allow_html=True)

# =====================
# Main App
# =====================
def main():
    # =====================
    # Streamlit Page Config
    # =====================
    st.set_page_config(page_title="Kommunale Mødeudtræk", layout="wide")

    # Add custom CSS for styling input fields
    add_custom_css()

    st.title("🔍 Kommunale Mødeudtræk")

    # Opret faner til navigation
    tab1, tab2 = st.tabs(["Søg i kommunale møder", "Populære emner"])

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

        query = st.text_input(
            "Søg efter et emne (f.eks. 'budget', 'lokalplan', 'fjernvarme', 'takster', 'ældreboliger', 'personalepolitik', 'udbuds', 'klimatilpasning', 'whistleblower', 'daginstitution', 'anlægsbevilling', 'garantistillelse'):",
            "")
        # Get unique municipalities from database
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT municipality FROM sourceview.foraisearch_with_search ORDER BY municipality")
        municipalities = ["Alle"] + [row['municipality'] for row in cur.fetchall()]
        cur.close()
        conn.close()

        municipality_filter = st.selectbox("Filtrér efter kommune:", municipalities)

        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Startdato (Valgfrit)", value=None)
        with col2:
            end_date = st.date_input("Slutdato (Valgfrit)", value=None)

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
                    # Refresh materialized view before searching
                    refresh_materialized_view()
                    # Perform search
                    docs, total_count = do_search(
                        query_text=query,
                        municipality=municipality_filter,
                        start_date=start_date,
                        end_date=end_date
                    )
                    show_results(docs, total_count)
                except Exception as e:
                    st.error(f"Der opstod en fejl: {e}")

        st.markdown("---")

    # =====================
    # Sektion for Populære Emner
    # =====================
    with tab2:
        st.subheader("Populære Emner")


        def fetch_all_categories():
            """
            Fetch category data from PostgreSQL
            """
            try:
                conn = get_db_connection()
                cur = conn.cursor()

                query = """
                SELECT 
                    category,
                    COUNT(*) as count
                FROM sourceview.foraisearch_with_search
                WHERE category IS NOT NULL
                GROUP BY category
                ORDER BY count DESC
                """

                cur.execute(query)
                results = cur.fetchall()
                return results
            except Exception as e:
                st.error(f"Error fetching categories: {e}")
                return []
            finally:
                if 'cur' in locals():
                    cur.close()
                if 'conn' in locals():
                    conn.close()


        def fetch_categories_by_municipality():
            """
            Fetch category data grouped by municipality
            """
            try:
                conn = get_db_connection()
                cur = conn.cursor()

                query = """
                SELECT 
                    municipality,
                    category,
                    COUNT(*) as count
                FROM sourceview.foraisearch_with_search
                WHERE category IS NOT NULL
                GROUP BY municipality, category
                ORDER BY municipality, count DESC
                """

                cur.execute(query)
                results = cur.fetchall()
                return results
            except Exception as e:
                st.error(f"Error fetching municipality categories: {e}")
                return []
            finally:
                if 'cur' in locals():
                    cur.close()
                if 'conn' in locals():
                    conn.close()


        def fetch_municipality_categories(municipality):
            """
            Fetch categories for a specific municipality
            """
            try:
                conn = get_db_connection()
                cur = conn.cursor()

                query = """
                SELECT 
                    category,
                    COUNT(*) as count
                FROM sourceview.foraisearch_with_search
                WHERE municipality = %s
                AND category IS NOT NULL
                GROUP BY category
                ORDER BY count DESC
                """

                cur.execute(query, [municipality])
                results = cur.fetchall()
                return results
            except Exception as e:
                st.error(f"Error fetching municipality categories: {e}")
                return []
            finally:
                if 'cur' in locals():
                    cur.close()
                if 'conn' in locals():
                    conn.close()


        def show_popular_categories():
            """
            Display overall category frequency
            """
            st.header("Populære Kategorier (Alle Kommuner)")
            categories = fetch_all_categories()

            if categories:
                # Convert to DataFrame
                df = pd.DataFrame(categories)

                # Display table
                st.dataframe(df)

                # Create bar chart
                st.bar_chart(df.set_index("category"))
            else:
                st.write("Ingen kategorier fundet.")


        def show_categories_by_municipality():
            """
            Display categories across municipalities
            """
            st.header("Kategorier efter Kommuner (Samlet Overblik)")
            results = fetch_categories_by_municipality()

            if results:
                # Convert to DataFrame
                df = pd.DataFrame(results)

                # Create Altair chart
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
            else:
                st.write("Ingen data fundet.")


        def show_categories_for_single_municipality():
            """
            Display categories for a selected municipality
            """
            st.header("Kategorier for Udvalgte Kommuner")

            # Get unique municipalities
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT municipality FROM sourceview.foraisearch_with_search ORDER BY municipality")
            municipalities = ["Alle"] + [row['municipality'] for row in cur.fetchall()]
            cur.close()
            conn.close()

            selected_muni = st.selectbox("Vælg en kommune:", municipalities)

            if selected_muni != "Alle":
                results = fetch_municipality_categories(selected_muni)
                if results:
                    df = pd.DataFrame(results)

                    # Show table
                    st.dataframe(df)

                    # Create bar chart
                    chart = alt.Chart(df).mark_bar().encode(
                        x=alt.X("count:Q", title="Antal"),
                        y=alt.Y("category:N", sort='-x', title="Kategori"),
                        tooltip=["category", "count"]
                    ).properties(
                        width=600,
                        height=400
                    )
                    st.altair_chart(chart, use_container_width=True)
                else:
                    st.write("Ingen kategorier fundet for denne kommune.")


        # Main function for tab 2
        def popular_topics_app():
            """
            Main function for the Popular Topics tab
            """
            st.title("Overblik over Populære Emner")

            # Show overall categories
            show_popular_categories()
            st.write("---")

            # Show categories by municipality
            show_categories_by_municipality()
            st.write("---")

            # Show categories for single municipality
            show_categories_for_single_municipality()

        popular_topics_app()

        #st.write("This section is currently under development.")

if __name__ == "__main__":
    main()
