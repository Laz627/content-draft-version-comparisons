import streamlit as st
import docx
import re
import openai
from itertools import zip_longest

# -----------------------------
# Streamlit Title & Instructions
# -----------------------------
st.title("📝 SEO Content Draft Comparator")
st.write(
    """
    **Purpose:**  
    Compare two versions of your `.docx` files (SEO brief, V1, V2, etc.) to see:

    - **Meta fields** like Title Tag, Meta Description, Existing URL (from paragraphs OR tables).
    - **Headings** (`H1:` through `H6:`).
    - **Paragraph-level** changes (optional AI summarization).
    
    **How to Use This App**  
    1. **Upload at least two .docx files**: For example, V1 and V2.  
    2. **Select which two versions** you want to compare.  
    3. **View the extracted Meta fields** and **Headings** side-by-side.  
    4. **See Added/Removed Headings**.  
    5. (Optional) Provide your **OpenAI API key** and enable AI summarization for a bullet-point analysis of how paragraphs changed.  
    """
)

# ----------------------------------
# 1. Optional: OpenAI API Key input
# ----------------------------------
openai_api_key = st.text_input("Enter your OpenAI API Key (optional):", type="password")
if openai_api_key:
    openai.api_key = openai_api_key

# ----------------------------------
# 2. Helpers to parse docx
# ----------------------------------

def clean_label_text(text):
    """
    Removes extra info like (Character limit: 60 max) from the label,
    lowercases, and strips.
    """
    # Remove bracketed content like (Character limit: 60 max)
    text = re.sub(r"\(Character limit.*?\)", "", text)
    # Also remove extraneous parentheses or leftover whitespace
    text = text.replace("(", "").replace(")", "")
    return text.strip().lower()

def parse_meta_fields_from_row(cells_text_list, meta):
    """
    Attempt to parse known meta fields if a row has a recognized label in one cell 
    and the associated value in the next cell. E.g.:
    Row Example: ["Title Tag (Character limit: 60 max)", "Top Sliding Glass Door...", "..."]
    
    We unify these:
    - "title tag" => "Meta Title"
    - "meta description" => "Meta Description"
    - "existing url" => "URL"
    - "url" => "URL" 
    - Possibly "author", "tags", etc. if needed
    """
    # Known triggers
    triggers = {
        "title tag": "Meta Title",
        "meta title": "Meta Title",        # fallback
        "meta description": "Meta Description",
        "existing url": "URL",
        "url": "URL"
    }
    
    # We'll look for a "label" cell, then the next cell is the "value"
    # Example: row might be 2 or 3 cells, we'll do pairwise scanning
    # for i in range(len(cells_text_list) - 1):
    #    label_cell, value_cell = cells_text_list[i], cells_text_list[i+1]
    
    # We'll allow multiple possible pairs. In practice, the first match is used.
    i = 0
    while i < len(cells_text_list) - 1:
        label_cell = cells_text_list[i]
        value_cell = cells_text_list[i + 1]
        if not label_cell.strip():
            i += 1
            continue
        
        # Clean label: remove (Character limit...) and to lowercase
        label_clean = clean_label_text(label_cell)
        
        # If label_clean is in triggers, we store the next cell
        if label_clean in triggers:
            field_key = triggers[label_clean]
            meta[field_key] = value_cell.strip()
            # Move 2 steps forward (we used i, i+1)
            i += 2
        else:
            i += 1

def parse_headings_or_paragraphs(text_line, headings, paragraphs):
    """
    If text_line looks like "H2: Some heading," store as heading. Else store as paragraph.
    """
    match = re.match(r'^(H[1-6]):\s*(.*)', text_line)
    if match:
        headings.append((match.group(1), match.group(2).strip()))
    else:
        paragraphs.append(text_line)

def extract_content(docx_file):
    """
    Extract meta fields, headings, paragraphs from a docx file.
    We parse both paragraphs and table rows.
    - For table rows: we parse known meta fields from label -> value pairs,
      then also parse leftover lines for headings or paragraphs.
    """
    doc = docx.Document(docx_file)
    
    meta = {"Meta Title": "", "Meta Description": "", "URL": ""}
    headings = []
    paragraphs = []
    
    # 1) Parse normal paragraphs first
    for para in doc.paragraphs:
        line = para.text.strip()
        if not line:
            continue
        # We'll do a quick check if it's a known meta label+value in one line
        # E.g. "Title Tag: Some Title"
        # If found, store. Otherwise, treat as heading or paragraph.
        if try_extract_inline_meta(line, meta):
            continue
        parse_headings_or_paragraphs(line, headings, paragraphs)
    
    # 2) Parse tables
    for table in doc.tables:
        # Each table has rows; each row has cells
        for row in table.rows:
            cells_text = []
            for cell in row.cells:
                # Combine all paragraphs in this cell
                cell_text = "\n".join([p.text.strip() for p in cell.paragraphs if p.text.strip()])
                cells_text.append(cell_text)
            
            # Attempt meta field extraction from row
            parse_meta_fields_from_row(cells_text, meta)
            
            # Also parse each cell's lines that might contain headings or paragraphs
            for cell_text in cells_text:
                # If we haven't used this cell as a meta field label->value, parse it line-by-line
                for line in cell_text.split("\n"):
                    # Check if inline meta?
                    if try_extract_inline_meta(line, meta):
                        continue
                    # else, heading or paragraph
                    parse_headings_or_paragraphs(line, headings, paragraphs)
    
    return meta, headings, paragraphs

def try_extract_inline_meta(line, meta):
    """
    Check if a single line contains something like 'Title Tag: Some Title'.
    If so, store it in meta and return True. Otherwise return False.
    """
    # Remove bracketed content e.g. (Character limit: 60 max)
    line_no_brackets = re.sub(r"\(Character limit.*?\)", "", line)
    line_no_brackets = line_no_brackets.strip()
    # Now see if we have a known prefix
    # e.g. "Title Tag:" or "Meta Description:" or "Existing URL:"
    # We'll unify to lowercase for label checks, but keep original for value
    possible_triggers = {
        "title tag": "Meta Title",
        "meta title": "Meta Title",
        "meta description": "Meta Description",
        "existing url": "URL",
        "url": "URL"
    }
    
    # match pattern like "Title Tag: Some Value"
    # We'll parse up to the first colon.
    if ":" in line_no_brackets:
        parts = line_no_brackets.split(":", 1)
        label = parts[0].lower().strip()
        value = parts[1].strip()
        if label in possible_triggers:
            meta[possible_triggers[label]] = value
            return True
    return False

# ----------------------------------
# 3. Heading Difference Detection
# ----------------------------------
def find_heading_differences(headings_v1, headings_v2):
    """
    Returns dict with sets: {"added": ..., "removed": ..., "common": ...}
    Using set difference on the string "H2: Bifold Doors".
    """
    set_v1 = set(f"{tag}: {txt}" for tag, txt in headings_v1)
    set_v2 = set(f"{tag}: {txt}" for tag, txt in headings_v2)
    added = set_v2 - set_v1
    removed = set_v1 - set_v2
    common = set_v1 & set_v2
    return {"added": added, "removed": removed, "common": common}

# ----------------------------------
# 4. AI Summarization (Paragraph-Level)
# ----------------------------------
def summarize_paragraph_changes(paragraphs_old, paragraphs_new):
    """
    Uses OpenAI to produce a pointed, digestible summary
    focusing on the more substantial paragraph changes.
    """
    if not openai.api_key:
        return "OpenAI API key not provided; cannot generate AI summary."
    
    # We'll keep the focus on paragraphs only, not headings
    prompt = (
        "You are an expert content analyst. Two versions of content exist. "
        "Focus ONLY on paragraph-level changes, expansions, style shifts, or new/removed info. "
        "Do NOT restate heading changes. Provide a short list or bullet points of the key differences.\n\n"
        "VERSION 1 PARAGRAPHS:\n"
        f"{'-'*50}\n{'\n'.join(paragraphs_old)}\n\n"
        "VERSION 2 PARAGRAPHS:\n"
        f"{'-'*50}\n{'\n'.join(paragraphs_new)}\n\n"
        "Now summarize how the paragraph content has changed."
    )
    
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",  # or gpt-3.5-turbo
        messages=[
            {"role": "system", "content": "You are an unbiased, detail-oriented content analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
    )
    return response["choices"][0]["message"]["content"].strip()

# ----------------------------------
# 5. Streamlit UI & Logic
# ----------------------------------
enable_ai = st.checkbox("Enable AI-powered paragraph-level analysis")

uploaded_files = st.file_uploader(
    "Upload .docx files (SEO brief, V1, V2, etc.):",
    accept_multiple_files=True,
    type=["docx"]
)

if uploaded_files and len(uploaded_files) >= 2:
    # Parse each file
    file_versions = {}
    for f in uploaded_files:
        meta, headings, paragraphs = extract_content(f)
        file_versions[f.name] = {
            "meta": meta,
            "headings": headings,
            "paragraphs": paragraphs
        }
    
    versions = list(file_versions.keys())
    v1 = st.selectbox("Select the FIRST version to compare:", versions)
    v2 = st.selectbox("Select the SECOND version to compare:", versions, 
                      index=min(1, len(versions)-1))
    
    if st.button("Compare Versions"):
        if v1 == v2:
            st.warning("You selected the same file for both versions. Please pick two different files.")
        else:
            meta_v1, heads_v1, paras_v1 = file_versions[v1]["meta"], file_versions[v1]["headings"], file_versions[v1]["paragraphs"]
            meta_v2, heads_v2, paras_v2 = file_versions[v2]["meta"], file_versions[v2]["headings"], file_versions[v2]["paragraphs"]
            
            # -----------------------
            # Accordions for each major section
            # -----------------------
            with st.expander("1) Metadata Changes", expanded=True):
                st.write("Comparing recognized meta fields from each version:")
                for field in ["Meta Title", "Meta Description", "URL"]:
                    old_val = meta_v1.get(field, "")
                    new_val = meta_v2.get(field, "")
                    st.write(f"**{field}**: `{old_val}` → `{new_val}`")
            
            with st.expander("2) Heading Comparisons", expanded=True):
                st.subheader("Side-by-Side Heading List")
                for (h1_tag, h1_text), (h2_tag, h2_text) in zip_longest(heads_v1, heads_v2, fillvalue=("", "")):
                    # Skip if truly empty
                    if not (h1_tag or h1_text or h2_tag or h2_text):
                        continue
                    st.write(f"- **{h1_tag or '—'}**: `{h1_text}` → **{h2_tag or '—'}**: `{h2_text}`")
                
                # Added / Removed Headings
                diffs = find_heading_differences(heads_v1, heads_v2)
                
                st.subheader("✅ Added vs. ❌ Removed Headings")
                if diffs["added"]:
                    st.write("**Added Headings**:")
                    for h in diffs["added"]:
                        st.write(f"- {h}")
                else:
                    st.write("*No newly added headings.*")
                
                if diffs["removed"]:
                    st.write("**Removed Headings**:")
                    for h in diffs["removed"]:
                        st.write(f"- {h}")
                else:
                    st.write("*No removed headings.*")
            
            with st.expander("3) Paragraph-Level Changes (AI-Powered)", expanded=True):
                if enable_ai:
                    if openai_api_key:
                        summary = summarize_paragraph_changes(paras_v1, paras_v2)
                        st.markdown(summary)
                    else:
                        st.warning("Please enter your OpenAI API key above to generate the AI summary.")
                else:
                    st.info("Enable AI analysis to see a bullet-point overview of paragraph differences.")
