import streamlit as st
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
import altair as alt
import time
import html  # Import the html module for escaping

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
    except Exception as e:
        st.error(f"Error refreshing materialized view: {e}")
    finally:
        if conn:
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
        # if start_date:
        #     query += " AND date::date >= %s"
        #     params.append(start_date)
        #
        # if end_date:
        #     query += " AND date::date <= %s"
        #     params.append(end_date)

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
        # if start_date:
        #     count_query += " AND date::date >= %s"
        #     count_params.append(start_date)
        #
        # if end_date:
        #     count_query += " AND date::date <= %s"
        #     count_params.append(end_date)

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


def show_results_in_cards(docs, total_count=None):
    """
    Viser en liste over dokumenter i Streamlit UI ved hjælp af et kortlayout.
    Uses html.escape() for safely displaying text.
    """
    current_query = st.session_state.get('search_query_app', "")

    if total_count is not None:
        st.write(f"**Antal resultater:** {total_count}")
        if total_count == 0 and current_query:
            st.info(
                f"Ingen resultater fundet for '{html.escape(current_query)}'. Prøv et andet søgeord eller juster dine filtre.")
        elif total_count == 0 and not current_query and st.session_state.get('search_initiated', False):
            st.info("Ingen resultater at vise. Indtast venligst et søgeord for at starte en søgning.")

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
                except:
                    pass
            elif hasattr(date_val, 'strftime'):
                date_val = date_val.strftime("%Y-%m-%d")

        municipality_val = doc.get("municipality", "N/A")
        subject_title_val = doc.get("subject_title", "Ingen emnetitel")
        summary_val = doc.get("summary", "Intet resumé tilgængeligt.")
        content_url = doc.get("content_url", "#")
        tags_val = doc.get("tags", [])
        decided = doc.get("decided_or_not", False)
        amount = str(doc.get("amount", ""))  # Ensure amount is a string for escaping

        max_summary_length = 250
        display_summary = summary_val
        if summary_val and len(summary_val) > max_summary_length:
            display_summary = summary_val[:max_summary_length] + "..."

        # Use html.escape() for all dynamic string content injected into HTML
        card_content = f"""
        <div class="result-card">
            <h3>{html.escape(subject_title_val)}</h3>
            <p class="meta-info">
                <strong>Kommune:</strong> {html.escape(municipality_val)} | 
                <strong>Dato:</strong> {html.escape(str(date_val)) or 'Ukendt'} |
                <strong>Beslutning truffet:</strong> {'Ja' if decided else 'Nej'}
                {f"| <strong>Bevilliget beløb:</strong> {html.escape(amount)} DKK" if amount else ""}
            </p>
            <p>{html.escape(display_summary)}</p>
        """

        processed_tags = []
        if tags_val:
            tags_html_parts = ["<div class='tags'>"]
            if isinstance(tags_val, str):
                processed_tags = [tag.strip() for tag in tags_val.split(',') if tag.strip()]
            elif isinstance(tags_val, list):
                processed_tags = [str(tag) for tag in tags_val if tag]

            for tag in processed_tags:
                tags_html_parts.append(f"<span>{html.escape(tag)}</span>")
            tags_html_parts.append("</div>")
            card_content += "".join(tags_html_parts)

        if content_url and content_url != "#":
            card_content += f"""
            <p style="margin-top: 15px;">
                <a href="{html.escape(content_url)}" target="_blank">📄 Se hele dokumentet</a>
            </p>
            """

        card_content += "</div>"
        st.markdown(card_content, unsafe_allow_html=True)

        with st.expander(f"Se flere detaljer for: \"{html.escape(subject_title_val[:50])}...\""):
            st.write(f"**Kommune:** {municipality_val}")
            st.write(f"**Fuld Resumé:** {summary_val}")
            st.write(f"**Emnetitel:** {subject_title_val}")
            st.write(f"**Emnebeskrivelse:** {doc.get('description', 'N/A')}")
            st.write(f"**Fremtidig handling:** {doc.get('future_action', 'N/A')}")
            if tags_val:
                if processed_tags:  # Use the already processed list of tags
                    st.write(f"**Tags for mødet generelt:** {', '.join(processed_tags)}")
                else:
                    st.write(f"**Tags for mødet generelt:** Ingen gyldige tags")
            else:
                st.write(f"**Tags for mødet generelt:** Ingen tags")

            st.write(f"**Beslutning truffet:** {'Ja' if decided else 'Nej'}")
            if amount:  # Use the string version of amount
                st.write(f"**Bevilliget beløb:** {amount} DKK")
            st.write(f"**Søgesætninger til dokumentet:** {doc.get('search_sentences', 'N/A')}")
            if content_url and content_url != "#":
                st.markdown(f"[📄 **Se hele dokumentet (igen)**]({content_url})")


def add_enhanced_custom_css():
    """Adds enhanced custom CSS to the Streamlit app for styling."""
    custom_css = """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
            html, body, [class*="st-"], .stTextInput input, .stSelectbox select, .stDateInput input {
               font-family: 'Inter', sans-serif !important;
            }
            .stTextInput input, .stSelectbox div[data-baseweb="select"] > div, .stDateInput input { 
                border: 1px solid #D0D5DD !important; 
                border-radius: 8px !important;        
                padding: 10px 12px !important;       
                box-shadow: 0 1px 2px rgba(0,0,0,0.05) !important;
                transition: border-color 0.2s ease, box-shadow 0.2s ease;
            }
            .stTextInput input:focus, .stSelectbox div[data-baseweb="select"] > div:focus-within, .stDateInput input:focus { 
                border-color: #4A90E2 !important; 
                box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.2) !important; 
            }
            .stButton>button {
                border: none !important;
                border-radius: 8px !important;
                color: white !important;
                background-color: #4A90E2 !important; 
                padding: 10px 18px !important; 
                font-weight: 500 !important;
                font-size: 0.95rem !important; 
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
                font-size: 0.95em !important; 
                font-weight: 500 !important; 
                color: #4B5563 !important; 
            }
            .stExpander {
                border: 1px solid #EAECEF !important;
                border-radius: 8px !important;
                background-color: #FFFFFF !important; 
                box-shadow: 0 1px 2px rgba(0,0,0,0.03); 
                margin-bottom: 0.75rem; 
            }
            .result-card {
                border: 1px solid #E0E4E7; 
                border-radius: 10px;
                padding: 18px; 
                margin-bottom: 18px; 
                background-color: #FFFFFF; 
                box-shadow: 0 2px 4px rgba(0,0,0,0.04); 
                transition: box-shadow 0.2s ease-in-out;
            }
            .result-card:hover {
                box-shadow: 0 5px 10px rgba(0,0,0,0.06); 
            }
            .result-card h3 { 
                margin-top: 0;
                margin-bottom: 8px; 
                color: #4A90E2; 
                font-size: 1.15rem; 
                font-weight: 600;
            }
            .result-card p {
                margin-bottom: 6px; 
                line-height: 1.55;
                color: #374151; 
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
                padding: 3px 7px; 
                border-radius: 12px; 
                font-size: 0.75rem; 
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
            .stSidebar {
                background-color: #FFFFFF; 
                padding: 1rem;
            }
            .stSidebar .stheader { 
                font-size: 1.2rem;
                color: #4A90E2;
            }
        </style>
    """
    st.markdown(custom_css, unsafe_allow_html=True)


@st.cache_data(ttl=3600)
def get_municipalities_list():
    """Fetches and caches the list of unique municipalities."""
    conn = get_db_connection()
    if not conn:
        return ["Alle"]
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT municipality FROM sourceview.foraisearch_with_search WHERE municipality IS NOT NULL ORDER BY municipality")
            municipalities = ["Alle"] + [row['municipality'] for row in cur.fetchall()]
            return municipalities
    except Exception as e:
        st.error(f"Error fetching municipalities: {e}")
        return ["Alle"]
    finally:
        if conn:
            conn.close()


def main():
    st.set_page_config(page_title="Kommunale Mødeudtræk", layout="wide")
    add_enhanced_custom_css()

    if 'search_query_app' not in st.session_state:
        st.session_state.search_query_app = ""
    if 'search_initiated' not in st.session_state:
        st.session_state.search_initiated = False

    st.title("🔍 Kommunale Mødeudtræk")
    tab1, tab2 = st.tabs(["Søg i kommunale møder", "Populære emner"])

    with st.sidebar:
        st.header("🛠️ Filter Indstillinger")
        municipalities = get_municipalities_list()
        municipality_filter_sidebar = st.selectbox(
            "Filtrér efter kommune:",
            municipalities,
            key="sidebar_municipality_filter"
        )
        st.markdown("---")
        st.markdown("App udviklet til at øge gennemsigtigheden i kommunale beslutninger.")

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
            "Søg efter et emne (f.eks. 'budget', 'lokalplan', ...):",
            st.session_state.search_query_app,
            key="main_query_input"
        )

        if st.button("🔎 Søg", key="search_button"):
            st.session_state.search_query_app = query_main
            st.session_state.search_initiated = True

            with st.spinner("Søger..."):
                try:
                    # refresh_materialized_view() # Optional, can be slow
                    docs, total_count = do_search(
                        query_text=st.session_state.search_query_app,
                        municipality=municipality_filter_sidebar,
                    )
                    show_results_in_cards(docs, total_count)
                except Exception as e:  # Catch general exceptions from do_search or show_results
                    st.error(f"Der opstod en fejl under søgningen: {e}")
                    print(f"Error in search button logic: {e}")  # Also print to console
        else:
            if st.session_state.search_initiated:
                # This logic might need refinement if you want to show stale results
                # For now, it clears results if search button isn't clicked again
                show_results_in_cards([], 0)
            else:
                show_results_in_cards([], None)

        st.markdown("---")

    with tab2:
        st.subheader("📊 Populære Emner")

        @st.cache_data(ttl=3600)
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
                    LIMIT 30; 
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
                    LIMIT 30; 
                    """
                    cur.execute(query, [selected_municipality])
                    return cur.fetchall()
            except Exception as e:
                st.error(f"Error fetching categories for {selected_municipality}: {e}")
                return []
            finally:
                if conn: conn.close()

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

        def show_categories_for_single_municipality_tab2():
            st.header("Kategorier for en Udvalgt Kommune")
            municipalities_list_tab2 = get_municipalities_list()
            if "Alle" in municipalities_list_tab2:
                municipalities_list_tab2_filtered = [m for m in municipalities_list_tab2 if m != "Alle"]
            else:
                municipalities_list_tab2_filtered = municipalities_list_tab2

            if not municipalities_list_tab2_filtered:
                st.warning("Ingen kommuner fundet i databasen.")
                return

            selected_muni = st.selectbox("Vælg en kommune:", municipalities_list_tab2_filtered, key="tab2_muni_select")

            if selected_muni:
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

        st.markdown("Her kan du få et overblik over, hvilke emner der oftest diskuteres i kommunale møder.")
        st.markdown("---")
        show_popular_categories_tab2()
        st.markdown("---")
        show_categories_for_single_municipality_tab2()


if __name__ == "__main__":
    if not all([DB_NAME, DB_USER, DB_PASSWORD, DB_HOST]):
        st.error(
            "Database configuration is missing. Please set DB_NAME, DB_USER, DB_PASSWORD, and DB_HOST environment variables.")
    else:
        main()
