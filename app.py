import streamlit as st
import os
import psycopg2
from psycopg2.extras import RealDictCursor
# from collections import Counter, defaultdict # Not explicitly used in the final version of popular topics
import pandas as pd
import altair as alt
# from duckduckgo_search import DDGS # Commented out in original
import time

# import random # Commented out in original (was for scrape_articles)
# from datetime import datetime # Not explicitly used for date formatting in final card version

# =====================
# Database Settings
# =====================
# It's good practice to ensure these are set in your environment
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")


def get_db_connection():
    """Create database connection"""
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
            cursor_factory=RealDictCursor
        )
        return conn
    except Exception as e:
        st.error(f"Database connection error: {e}. Please check your environment variables and database status.")
        return None


# =====================
# Web Scraping Funktion (Commented out as in original)
# =====================
# def scrape_articles(query, count=3, max_retries=3):
#     # ... (original commented out code) ...
#     pass


# =====================
# Søgefunktionalitet
# =====================
def refresh_materialized_view():
    """Refresh the materialized view"""
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW sourceview.foraisearch_with_search")
            conn.commit()
            # st.toast("Materialized view refreshed.", icon="🔄") # Optional feedback
    except Exception as e:
        st.error(f"Error refreshing materialized view: {e}")
    finally:
        if conn:
            conn.close()


def do_search(query_text="", municipality=None, start_date=None, end_date=None, limit=20):
    """
    Perform full-text search using PostgreSQL
    """
    conn = get_db_connection()
    if not conn:
        return [], 0

    results = []
    total_count = 0

    try:
        with conn.cursor() as cur:
            # Build the query
            # This SQL query is complex and directly from your original code.
            # Ensure 'search_vector' column and 'pg_trgm' extension (for similarity) are set up in your PostgreSQL.
            query_sql = """
                SELECT  
                    t.id, t.municipality, t.date, t.participants, t.guests, t.title,  
                    t.summary, t.tags, t.content_url, t.category, t.search_sentences,
                    t.decided_or_not, t.future_action, t.description, t.subject_title, t.amount,
                    COALESCE(ts_rank_score, 0) as ts_rank_score,
                    COALESCE(similarity_score, 0) as similarity_score
                FROM (
                    SELECT  
                        *,
                        ts_rank(search_vector, plainto_tsquery('danish', %(query_text)s)) as ts_rank_score,
                        similarity(
                            ((((((((COALESCE(municipality, '')::text || ' ') ||  
                            COALESCE(title, '')::text) || ' ') ||  
                            COALESCE(category, '')::text) || ' ') ||  
                            COALESCE(description, '')::text) || ' ') ||  
                            COALESCE(future_action, '')::text) || ' ') ||  
                            COALESCE(subject_title, '')::text),
                            %(query_text)s
                        ) as similarity_score
                    FROM sourceview.foraisearch_with_search
                ) t
                WHERE 
            """

            params = {'query_text': query_text, 'limit': limit}

            # Add wildcard search for even better matches
            wildcard_query_parts = [f"{word}:*" for word in query_text.split() if word]  # Ensure word is not empty
            wildcard_query = " | ".join(wildcard_query_parts) if wildcard_query_parts else ""

            where_conditions = []
            if query_text:  # Only add text search conditions if query_text is provided
                where_conditions.extend([
                    "t.search_vector @@ plainto_tsquery('danish', %(query_text)s)",
                    "t.similarity_score > 0.05"  # Adjust threshold as needed
                ])
                if wildcard_query:
                    where_conditions.append("t.search_vector @@ to_tsquery('danish', %(wildcard_query)s)")
                    params['wildcard_query'] = wildcard_query

            if not where_conditions and (
                    municipality and municipality != "Alle"):  # Handle case where only municipality is filtered
                query_sql += " 1=1 "  # Start with a true condition if no text search
            elif not where_conditions:  # No search text and no municipality filter
                query_sql += " 1=0 "  # Return no results if no search criteria (or handle as desired)
            else:
                query_sql += " OR ".join(where_conditions)

            # Add filters
            if municipality and municipality != "Alle":
                query_sql += " AND municipality = %(municipality)s"
                params['municipality'] = municipality

            # if start_date: # Keep commented if not using
            #     query_sql += " AND date::date >= %(start_date)s"
            #     params['start_date'] = start_date
            #
            # if end_date: # Keep commented if not using
            #     query_sql += " AND date::date <= %(end_date)s"
            #     params['end_date'] = end_date

            # Add ordering and limit
            # The ORDER BY clause from your original code is quite complex.
            # Ensure it's correct and doesn't cause issues if query_text is empty.
            if query_text:  # Only order by rank/similarity if there's a query text
                query_sql += """
                ORDER BY ((ts_rank(search_vector, plainto_tsquery('danish', %(query_text)s))) + (similarity(
                                (((((((((COALESCE(municipality, '')::text || ' ') ||  
                                COALESCE(title, '')::text) || ' ') ||  
                                COALESCE(category, '')::text) || ' ') ||  
                                COALESCE(description, '')::text) || ' ') ||  
                                COALESCE(future_action, '')::text) || ' ') ||  
                                COALESCE(subject_title, '')::text),
                                %(query_text)s
                            )) * 0.8) DESC 
                """
            else:  # Default order if no search text (e.g., by date)
                query_sql += " ORDER BY date DESC NULLS LAST "

            query_sql += " LIMIT %(limit)s"

            # Execute search
            cur.execute(query_sql, params)
            results = cur.fetchall()

            # Count query for total matches - reusing parts of the main query logic
            count_query_sql = "SELECT COUNT(*) FROM sourceview.foraisearch_with_search t WHERE "
            count_params = {'query_text': query_text}

            if not where_conditions and (municipality and municipality != "Alle"):
                count_query_sql += " 1=1 "
            elif not where_conditions:
                count_query_sql += " 1=0 "
            else:
                count_query_sql += " OR ".join(where_conditions)  # Re-use where_conditions from above
                if wildcard_query and 'wildcard_query' not in count_params:  # Ensure wildcard_query is in params if used
                    count_params['wildcard_query'] = wildcard_query

            if municipality and municipality != "Alle":
                count_query_sql += " AND municipality = %(municipality)s"
                count_params['municipality'] = municipality

            # if start_date: # Keep commented if not using
            #     count_query_sql += " AND date::date >= %(start_date)s"
            #     count_params['start_date'] = start_date
            # if end_date: # Keep commented if not using
            #     count_query_sql += " AND date::date <= %(end_date)s"
            #     count_params['end_date'] = end_date

            cur.execute(count_query_sql, count_params)
            total_count = cur.fetchone()['count']

    except Exception as e:
        st.error(f"Search error: {e}")
        return [], 0  # Return empty results and 0 count on error
    finally:
        if conn:
            conn.close()
    return results, total_count


def show_results_in_cards(docs, total_count=None):
    """
    Viser en liste over dokumenter i Streamlit UI ved hjælp af et kortlayout.
    """
    current_query = st.session_state.get('search_query_app', "")

    if total_count is not None:
        st.write(f"**Antal resultater:** {total_count}")
        if total_count == 0 and current_query:
            st.info(f"Ingen resultater fundet for '{current_query}'. Prøv et andet søgeord eller juster dine filtre.")
        elif total_count == 0 and not current_query and st.session_state.get('search_initiated', False):
            st.info("Ingen resultater at vise. Indtast venligst et søgeord for at starte en søgning.")
        # Do not show "Ingen resultater at vise" if no search has been made yet.

    if not docs and total_count == 0 and not current_query and not st.session_state.get('search_initiated', False):
        st.markdown(
            "<p style='text-align: center; color: #777; margin-top: 20px;'><i>Brug søgefeltet og filtrene i sidebaren for at finde mødereferater.</i></p>",
            unsafe_allow_html=True)

    for i, doc in enumerate(docs):
        date_val = doc.get("date", "")
        if date_val:
            if isinstance(date_val, str):
                try:
                    date_val = date_val.split("T")[0]
                except:  # pylint: disable=bare-except
                    pass
                    # Assuming date might be datetime object from DB, format it.
            # If it's already a string from RealDictCursor, this might not be needed or might error.
            # Check the actual type of doc.get("date")
            elif hasattr(date_val, 'strftime'):  # Check if it's a date/datetime object
                date_val = date_val.strftime("%Y-%m-%d")

        municipality_val = doc.get("municipality", "N/A")
        subject_title_val = doc.get("subject_title", "Ingen emnetitel")
        summary_val = doc.get("summary", "Intet resumé tilgængeligt.")
        content_url = doc.get("content_url", "#")
        tags_val = doc.get("tags", [])  # Expecting a list or None
        decided = doc.get("decided_or_not", False)
        amount = doc.get("amount", "")

        max_summary_length = 250
        display_summary = summary_val
        if summary_val and len(summary_val) > max_summary_length:
            display_summary = summary_val[:max_summary_length] + "..."

        card_content = f"""
        <div class="result-card">
            <h3>{st.markdown.escape(subject_title_val)}</h3>
            <p class="meta-info">
                <strong>Kommune:</strong> {st.markdown.escape(municipality_val)} | 
                <strong>Dato:</strong> {st.markdown.escape(str(date_val)) or 'Ukendt'} |
                <strong>Beslutning truffet:</strong> {'Ja' if decided else 'Nej'}
                {f"| <strong>Bevilliget beløb:</strong> {st.markdown.escape(str(amount))} DKK" if amount else ""}
            </p>
            <p>{st.markdown.escape(display_summary)}</p>
        """

        if tags_val:  # tags_val should ideally be a list of strings
            tags_html = "<div class='tags'>"
            processed_tags = []
            if isinstance(tags_val, str):  # Handle if tags are a single comma-separated string
                processed_tags = [tag.strip() for tag in tags_val.split(',') if tag.strip()]
            elif isinstance(tags_val, list):
                processed_tags = [str(tag) for tag in tags_val if tag]  # Ensure tags are strings

            for tag in processed_tags:
                tags_html += f"<span>{st.markdown.escape(tag)}</span>"
            tags_html += "</div>"
            card_content += tags_html

        if content_url and content_url != "#":
            card_content += f"""
            <p style="margin-top: 15px;">
                <a href="{st.markdown.escape(content_url)}" target="_blank">📄 Se hele dokumentet</a>
            </p>
            """

        card_content += "</div>"
        st.markdown(card_content, unsafe_allow_html=True)

        # Optional Expander for more details
        with st.expander(f"Se flere detaljer for: \"{subject_title_val[:50]}...\""):
            st.write(f"**Kommune:** {municipality_val}")
            st.write(f"**Fuld Resumé:** {summary_val}")
            st.write(f"**Emnetitel:** {subject_title_val}")
            st.write(f"**Emnebeskrivelse:** {doc.get('description', 'N/A')}")
            st.write(f"**Fremtidig handling:** {doc.get('future_action', 'N/A')}")
            if tags_val:
                if isinstance(processed_tags, list) and processed_tags:
                    st.write(f"**Tags for mødet generelt:** {', '.join(processed_tags)}")
                elif isinstance(tags_val, str) and tags_val:  # Fallback for original string format
                    st.write(f"**Tags for mødet generelt:** {tags_val}")
                else:
                    st.write(f"**Tags for mødet generelt:** Ingen tags")

            st.write(f"**Beslutning truffet:** {'Ja' if decided else 'Nej'}")
            if amount:
                st.write(f"**Bevilliget beløb:** {amount} DKK")
            st.write(f"**Søgesætninger til dokumentet:** {doc.get('search_sentences', 'N/A')}")
            if content_url and content_url != "#":
                st.markdown(f"[📄 **Se hele dokumentet (igen)**]({content_url})")


def add_enhanced_custom_css():
    """Adds enhanced custom CSS to the Streamlit app for styling."""
    # CSS from the previous immersive artifact
    custom_css = """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
            html, body, [class*="st-"], .stTextInput input, .stSelectbox select, .stDateInput input {
               font-family: 'Inter', sans-serif !important;
            }
            .stTextInput input, .stSelectbox div[data-baseweb="select"] > div, .stDateInput input { /* Adjusted .stSelectbox selector */
                border: 1px solid #D0D5DD !important; 
                border-radius: 8px !important;        
                padding: 10px 12px !important;       /* Adjusted padding for consistency */
                box-shadow: 0 1px 2px rgba(0,0,0,0.05) !important;
                transition: border-color 0.2s ease, box-shadow 0.2s ease;
            }
            .stTextInput input:focus, .stSelectbox div[data-baseweb="select"] > div:focus-within, .stDateInput input:focus { /* Adjusted .stSelectbox selector */
                border-color: #4A90E2 !important; 
                box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.2) !important; 
            }
            .stButton>button {
                border: none !important;
                border-radius: 8px !important;
                color: white !important;
                background-color: #4A90E2 !important; 
                padding: 10px 18px !important; /* Adjusted padding */
                font-weight: 500 !important;
                font-size: 0.95rem !important; /* Adjusted font size */
                transition: background-color 0.2s ease, transform 0.1s ease;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.06);
            }
            .stButton>button:hover {
                background-color: #357ABD !important; 
                transform: translateY(-1px); 
            }
            .stButton>button:active {
                background-color: #2A6496 !important; 
                transform: translateY(0px);
            }
            .stExpanderHeader {
                font-size: 0.95em !important; /* Slightly smaller for less emphasis */
                font-weight: 500 !important; /* Medium weight */
                color: #4B5563 !important; 
            }
            .stExpander {
                border: 1px solid #EAECEF !important;
                border-radius: 8px !important;
                background-color: #FFFFFF !important; 
                box-shadow: 0 1px 2px rgba(0,0,0,0.03); /* Softer shadow */
                margin-bottom: 0.75rem; 
            }
            .result-card {
                border: 1px solid #E0E4E7; /* Slightly lighter border */
                border-radius: 10px;
                padding: 18px; /* Adjusted padding */
                margin-bottom: 18px; /* Adjusted margin */
                background-color: #FFFFFF; 
                box-shadow: 0 2px 4px rgba(0,0,0,0.04); /* Softer shadow */
                transition: box-shadow 0.2s ease-in-out;
            }
            .result-card:hover {
                box-shadow: 0 5px 10px rgba(0,0,0,0.06); /* Enhanced hover shadow */
            }
            .result-card h3 { 
                margin-top: 0;
                margin-bottom: 8px; /* Reduced margin */
                color: #4A90E2; 
                font-size: 1.15rem; /* Adjusted size */
                font-weight: 600;
            }
            .result-card p {
                margin-bottom: 6px; /* Reduced margin */
                line-height: 1.55;
                color: #374151; /* Slightly darker text for better readability */
                font-size: 0.9rem;
            }
            .result-card .meta-info { 
                font-size: 0.85rem;
                color: #6B7280;
                margin-bottom: 12px;
            }
            .result-card .tags span {
                background-color: #E0E7FF; 
                color: #3730A3; 
                padding: 3px 7px; /* Adjusted padding */
                border-radius: 12px; 
                font-size: 0.75rem; /* Adjusted size */
                margin-right: 5px;
                display: inline-block;
                margin-bottom: 5px;
                font-weight: 500;
            }
            .result-card a {
                color: #357ABD; 
                text-decoration: none;
                font-weight: 500;
            }
            .result-card a:hover {
                text-decoration: underline;
            }
            button[data-baseweb="tab"] { 
                font-size: 1rem !important;
                padding: 10px 18px !important;
                font-weight: 500 !important;
                color: #4B5563 !important; 
                border-bottom: 2px solid transparent !important; 
                transition: color 0.2s ease, border-color 0.2s ease;
            }
            button[data-baseweb="tab"][aria-selected="true"] {
                color: #4A90E2 !important; 
                border-bottom: 2px solid #4A90E2 !important; 
                font-weight: 600 !important;
            }
            .stApp {
                 background-color: #F0F2F6; 
            }
            /* Sidebar styling */
            .stSidebar {
                background-color: #FFFFFF; /* Or your secondaryBackgroundColor */
                padding: 1rem;
            }
            .stSidebar .stheader { /* Target headers in sidebar if needed */
                font-size: 1.2rem;
                color: #4A90E2;
            }
        </style>
    """
    st.markdown(custom_css, unsafe_allow_html=True)


# =====================
# Main App
# =====================
@st.cache_data(ttl=3600)  # Cache for 1 hour
def get_municipalities_list():
    """Fetches and caches the list of unique municipalities."""
    conn = get_db_connection()
    if not conn:
        return ["Alle"]  # Default if DB connection fails
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT municipality FROM sourceview.foraisearch_with_search WHERE municipality IS NOT NULL ORDER BY municipality")
            municipalities = ["Alle"] + [row['municipality'] for row in cur.fetchall()]
            return municipalities
    except Exception as e:
        st.error(f"Error fetching municipalities: {e}")
        return ["Alle"]  # Default on error
    finally:
        if conn:
            conn.close()


def main():
    # =====================
    # Streamlit Page Config
    # =====================
    st.set_page_config(page_title="Kommunale Mødeudtræk", layout="wide")

    # Add custom CSS for styling
    add_enhanced_custom_css()

    # Initialize session state variables if they don't exist
    if 'search_query_app' not in st.session_state:
        st.session_state.search_query_app = ""
    if 'search_initiated' not in st.session_state:
        st.session_state.search_initiated = False

    st.title("🔍 Kommunale Mødeudtræk")

    # Opret faner til navigation
    tab1, tab2 = st.tabs(["Søg i kommunale møder", "Populære emner"])

    # =====================
    # Sidebar for Filters (Tab 1)
    # =====================
    with st.sidebar:
        st.header("🛠️ Filter Indstillinger")

        # Get unique municipalities from database (cached)
        municipalities = get_municipalities_list()
        municipality_filter_sidebar = st.selectbox(
            "Filtrér efter kommune:",
            municipalities,
            key="sidebar_municipality_filter"
        )

        # st.subheader("Datoperiode (Valgfri)") # Uncomment if you re-add date filters
        # start_date_sidebar = st.date_input("Startdato", value=None, key="sidebar_start_date")
        # end_date_sidebar = st.date_input("Slutdato", value=None, key="sidebar_end_date")

        st.markdown("---")
        st.markdown("App udviklet til at øge gennemsigtigheden i kommunale beslutninger.")

    # =====================
    # Hovedsøgefunktion (Tab 1)
    # =====================
    with tab1:
        with st.expander("### ℹ️ Sådan bruger du appen (Klik for at se mere)"):
            st.markdown("""
                Denne **Kommunale Mødeudtræk** app gør det nemt at **søge og udforske kommunale mødereferater** fra forskellige danske kommuner.

                ### 🔍 **Sådan bruger du appen:**
                1️⃣ **Indtast søgeord** i feltet nedenfor (f.eks. *"bolig"*, *"budget"*, *"miljø"*).  
                2️⃣ **Vælg filtre** i menuen til venstre (kommune, evt. dato).  
                3️⃣ Klik på **"🔎 Søg"** for at finde relevante møder.  
                4️⃣ **Gennemse resultaterne** som vises i kortformat. Klik på et kort for at se flere detaljer. 
                5️⃣ Klik på **"Se hele dokumentet"** for at læse originalreferatet.  

                📌 **Formål:** Øget gennemsigtighed i kommunale beslutninger og let adgang til information om lokalpolitik.
            """)

        st.subheader("Indtast dit søgeord her:")
        query_main = st.text_input(
            "Søg efter et emne (f.eks. 'budget', 'lokalplan', 'fjernvarme', 'takster', 'ældreboliger', 'personalepolitik', 'udbuds', 'klimatilpasning', 'whistleblower', 'daginstitution', 'anlægsbevilling', 'garantistillelse'):",
            st.session_state.search_query_app,  # Persist query in input field
            key="main_query_input"
        )

        if st.button("🔎 Søg", key="search_button"):
            st.session_state.search_query_app = query_main  # Update session state with current query
            st.session_state.search_initiated = True  # Mark that a search has been performed

            with st.spinner("Søger..."):
                try:
                    # Refresh materialized view before searching (optional, can be slow)
                    # Consider if this needs to be run on every search or less frequently
                    # refresh_materialized_view()

                    docs, total_count = do_search(
                        query_text=st.session_state.search_query_app,
                        municipality=municipality_filter_sidebar,  # Use filter from sidebar
                        # start_date=start_date_sidebar, # Uncomment if using date filters
                        # end_date=end_date_sidebar
                    )
                    show_results_in_cards(docs, total_count)
                except Exception as e:
                    st.error(f"Der opstod en fejl under søgningen: {e}")
        else:
            # Show results based on session state if a search was previously initiated
            # This allows results to persist if user interacts with other elements (e.g. expander)
            # without re-clicking search
            if st.session_state.search_initiated:
                # Potentially re-fetch or just display stored results if complex
                # For now, we'll rely on the user clicking search again to refresh if filters change
                # Or, you could store 'docs' and 'total_count' in session_state
                # This part is tricky with Streamlit's rerun model.
                # The simplest is to require search button click for new results.
                # The current show_results_in_cards will show "no results" or initial message
                # if docs are not passed.
                show_results_in_cards([], 0)  # Show empty state until search button is clicked
            else:
                show_results_in_cards([], None)  # Initial state before any search

        st.markdown("---")

    # =====================
    # Sektion for Populære Emner (Tab 2)
    # =====================
    with tab2:
        st.subheader("📊 Populære Emner")

        # Functions for fetching category data (ensure these use get_db_connection properly)
        @st.cache_data(ttl=3600)  # Cache for 1 hour
        def fetch_all_categories_tab2():
            conn = get_db_connection()
            if not conn: return []
            try:
                with conn.cursor() as cur:
                    query = """
                    SELECT category, COUNT(*) as count
                    FROM sourceview.foraisearch_with_search
                    WHERE category IS NOT NULL AND TRIM(category) <> ''
                    GROUP BY category
                    ORDER BY count DESC
                    LIMIT 30; -- Limit for better visualization
                    """
                    cur.execute(query)
                    return cur.fetchall()
            except Exception as e:
                st.error(f"Error fetching all categories: {e}")
                return []
            finally:
                if conn: conn.close()

        @st.cache_data(ttl=3600)
        def fetch_categories_by_municipality_tab2():
            conn = get_db_connection()
            if not conn: return []
            try:
                with conn.cursor() as cur:
                    query = """
                    SELECT municipality, category, COUNT(*) as count
                    FROM sourceview.foraisearch_with_search
                    WHERE category IS NOT NULL AND TRIM(category) <> '' AND municipality IS NOT NULL
                    GROUP BY municipality, category
                    ORDER BY municipality, count DESC;
                    """
                    cur.execute(query)
                    # Further processing might be needed if this dataset is too large for direct Altair rendering
                    return cur.fetchall()
            except Exception as e:
                st.error(f"Error fetching categories by municipality: {e}")
                return []
            finally:
                if conn: conn.close()

        @st.cache_data(ttl=3600)
        def fetch_municipality_categories_tab2(selected_municipality):
            conn = get_db_connection()
            if not conn: return []
            try:
                with conn.cursor() as cur:
                    query = """
                    SELECT category, COUNT(*) as count
                    FROM sourceview.foraisearch_with_search
                    WHERE municipality = %s
                    AND category IS NOT NULL AND TRIM(category) <> ''
                    GROUP BY category
                    ORDER BY count DESC
                    LIMIT 30; -- Limit for better visualization
                    """
                    cur.execute(query, [selected_municipality])
                    return cur.fetchall()
            except Exception as e:
                st.error(f"Error fetching categories for {selected_municipality}: {e}")
                return []
            finally:
                if conn: conn.close()

        # --- Display functions for Tab 2 ---
        def show_popular_categories_tab2():
            st.header("Mest Diskuterede Kategorier (Alle Kommuner)")
            categories_data = fetch_all_categories_tab2()
            if categories_data:
                df = pd.DataFrame(categories_data)
                if not df.empty:
                    chart = alt.Chart(df).mark_bar().encode(
                        x=alt.X('count:Q', title='Antal Møder'),
                        y=alt.Y('category:N', sort='-x', title='Kategori'),
                        tooltip=['category', 'count']
                    ).properties(
                        title='Top Kategorier på tværs af alle kommuner'
                    )
                    st.altair_chart(chart, use_container_width=True)
                    with st.expander("Se rådata (Top Kategorier)"):
                        st.dataframe(df)
                else:
                    st.write("Ingen kategoridata fundet.")
            else:
                st.write("Ingen kategorier fundet eller fejl ved hentning.")

        def show_categories_by_municipality_tab2():
            st.header("Kategorier fordelt på Kommuner (Udsnit)")
            st.write("Viser de mest populære kategorier for et udsnit af kommuner for overblikkets skyld.")
            # This can be very large. Consider sampling or limiting municipalities for the overview chart.
            # For now, we fetch all and let Altair handle it, but it might be slow/cluttered.
            # A better approach might be to select top N municipalities or let user choose.
            results = fetch_categories_by_municipality_tab2()
            if results:
                df = pd.DataFrame(results)
                if not df.empty:
                    # Example: Top 5 categories per municipality for clarity
                    df_top_n = df.groupby('municipality').apply(lambda x: x.nlargest(5, 'count')).reset_index(drop=True)

                    chart = alt.Chart(df_top_n).mark_bar().encode(
                        x=alt.X('count:Q', title='Antal Møder'),
                        y=alt.Y('category:N', sort='-x', title='Kategori'),
                        color='municipality:N',
                        tooltip=['municipality', 'category', 'count'],
                        facet=alt.Facet('municipality:N', columns=3)  # Facet per municipality
                    ).properties(
                        title='Top 5 Kategorier pr. Kommune (Udsnit)',
                        width=200,  # Width per facet
                        height=150  # Height per facet
                    )
                    st.altair_chart(chart)  # Not using use_container_width with facetting
                    with st.expander("Se rådata (Kategorier pr. kommune)"):
                        st.dataframe(df)  # Show all data in expander
                else:
                    st.write("Ingen data fundet.")
            else:
                st.write("Ingen data fundet eller fejl ved hentning.")

        def show_categories_for_single_municipality_tab2():
            st.header("Kategorier for en Udvalgt Kommune")
            municipalities_list_tab2 = get_municipalities_list()  # Use cached list
            # Remove "Alle" option for this specific selector if it exists
            if "Alle" in municipalities_list_tab2:
                municipalities_list_tab2_filtered = [m for m in municipalities_list_tab2 if m != "Alle"]
            else:
                municipalities_list_tab2_filtered = municipalities_list_tab2

            if not municipalities_list_tab2_filtered:
                st.warning("Ingen kommuner fundet i databasen.")
                return

            selected_muni = st.selectbox("Vælg en kommune:", municipalities_list_tab2_filtered, key="tab2_muni_select")

            if selected_muni:  # No "Alle" option here
                results = fetch_municipality_categories_tab2(selected_muni)
                if results:
                    df = pd.DataFrame(results)
                    if not df.empty:
                        chart = alt.Chart(df).mark_bar().encode(
                            x=alt.X("count:Q", title="Antal Møder"),
                            y=alt.Y("category:N", sort='-x', title="Kategori"),
                            tooltip=["category", "count"]
                        ).properties(
                            title=f"Top Kategorier i {selected_muni}"
                        )
                        st.altair_chart(chart, use_container_width=True)
                        with st.expander(f"Se rådata for {selected_muni}"):
                            st.dataframe(df)
                    else:
                        st.write(f"Ingen kategorier fundet for {selected_muni}.")
                else:
                    st.write(f"Ingen kategorier fundet for {selected_muni} eller fejl ved hentning.")

        # --- Structure for Tab 2 ---
        st.markdown("Her kan du få et overblik over, hvilke emner der oftest diskuteres i kommunale møder.")
        st.markdown("---")
        show_popular_categories_tab2()
        st.markdown("---")
        # show_categories_by_municipality_tab2() # This can be very large, consider if it's needed or how to best display it
        # st.markdown("---")
        show_categories_for_single_municipality_tab2()


if __name__ == "__main__":
    # Basic check for essential DB env vars
    if not all([DB_NAME, DB_USER, DB_PASSWORD, DB_HOST]):
        st.error(
            "Database configuration is missing. Please set DB_NAME, DB_USER, DB_PASSWORD, and DB_HOST environment variables.")
    else:
        main()

