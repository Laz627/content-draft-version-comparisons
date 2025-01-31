import streamlit as st
import docx
import re
import openai
from itertools import zip_longest

# -------------------------------------------------------------------
# Streamlit Title & Instructions
# -------------------------------------------------------------------
st.title("📝 SEO Content Draft Comparator")

st.write(
    """
    **Purpose**  
    Compare `.docx` files (e.g., an SEO brief vs. V1 vs. V2) to see:
    - **Meta fields** (Title Tag / Meta Title, Meta Description, URL) 
    - **Headings** (`H1:` - `H6:`)
    - **Paragraph-level** content changes via optional AI summaries.

    **How to Use**  
    1. **Upload at least two .docx files**: (SEO Brief, V1, V2, etc.).  
    2. **Select which two** files to compare from the dropdowns.  
    3. **Expand** the accordions to see metadata, headings, and added/removed headings.  
    4. (Optional) Provide your **OpenAI API key** and enable AI summarization for a more pointed paragraph-level analysis.
    """
)

# -------------------------------------------------------------------
# 1. OpenAI API Key (Optional)
# -------------------------------------------------------------------
openai_api_key = st.text_input("Enter your OpenAI API Key (optional):", type="password")
if openai_api_key:
    openai.api_key = openai_api_key

enable_ai = st.checkbox("Enable AI-powered paragraph-level analysis")

# -------------------------------------------------------------------
# 2. Helper: Clean label text (removing bracketed notes, etc.)
# -------------------------------------------------------------------
def clean_label_text(txt):
    # Remove (Character limit: something)
    txt = re.sub(r"\(Character limit.*?\)", "", txt)
    txt = txt.replace("(", "").replace(")", "")
    return txt.strip().lower()

# -------------------------------------------------------------------
# 3. Parsing lines from paragraphs (SEO Brief style)
# -------------------------------------------------------------------
def parse_paragraphs_for_meta(lines, meta, headings, paragraphs):
    """
    If a line is "Meta Title" (or "Meta Description", "H1", "URL"), then
    the next non-label line is used as the value. 
    Otherwise, check if it's an inline meta (e.g. "URL: https://...") or a heading "H2: Some heading."
    Everything else -> paragraphs.
    """
    possible_labels = {
        "meta title": "Meta Title",
        "meta description": "Meta Description",
        "h1": "H1",   # Some users store the main heading in meta, but you might prefer to handle as a normal heading.
        "url": "URL"
    }
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        
        # 1) If line exactly matches a label (e.g. "Meta Title")
        clabel = clean_label_text(line)
        if clabel in possible_labels:
            label_key = possible_labels[clabel]  # e.g. "Meta Title"
            # Attempt to get next line as the value
            if i + 1 < len(lines):
                next_line = lines[i+1].strip()
                next_label = clean_label_text(next_line)
                # If the next line is NOT also a label, treat it as the value
                if next_label not in possible_labels:
                    meta[label_key] = next_line
                    i += 2
                    continue
            i += 1
            continue
        
        # 2) Check if inline meta "URL: something"
        if try_extract_inline_meta(line, meta):
            i += 1
            continue
        
        # 3) If "H2: Some heading"
        match = re.match(r'^(H[1-6]):\s*(.*)', line, flags=re.IGNORECASE)
        if match:
            headings.append((match.group(1).upper(), match.group(2).strip()))
            i += 1
            continue
        
        # Otherwise, treat as paragraph
        paragraphs.append(line)
        i += 1

# -------------------------------------------------------------------
# 4. Table parsing for V1/V2 style
# -------------------------------------------------------------------
def parse_table_for_meta_and_others(table, meta, headings, paragraphs):
    """
    We scan each row. If we find known meta labels in one cell, 
    we take the next cell's text as the value. We also parse 
    each cell line for headings or inline meta.
    """
    for row in table.rows:
        # Gather cell texts in a list
        cell_texts = [cell.text.strip() for cell in row.cells]
        # Attempt row-based label->value detection
        parse_meta_fields_from_row(cell_texts, meta)
        
        # Also parse line-by-line for headings or inline meta
        for ctext in cell_texts:
            # Possibly multiple lines in a single cell
            for line in ctext.split("\n"):
                line_stripped = line.strip()
                if line_stripped:
                    # Try inline meta
                    if try_extract_inline_meta(line_stripped, meta):
                        continue
                    # Check heading
                    match = re.match(r'^(H[1-6]):\s*(.*)', line_stripped, flags=re.IGNORECASE)
                    if match:
                        headings.append((match.group(1).upper(), match.group(2).strip()))
                    else:
                        paragraphs.append(line_stripped)

# -------------------------------------------------------------------
# 5. Row-based meta detection
# -------------------------------------------------------------------
def parse_meta_fields_from_row(cells_text_list, meta):
    """
    If a cell is recognized as a known label, the next cell is stored as value.
    For example: ["Meta Title", "Top Sliding Glass..."]
    """
    # Known triggers
    triggers = {
        "meta title": "Meta Title",
        "meta description": "Meta Description",
        "title tag": "Meta Title",         # sometimes called Title Tag
        "existing url": "URL",
        "url": "URL",
        "h1": "H1"
    }
    
    i = 0
    while i < len(cells_text_list) - 1:
        label_cell = clean_label_text(cells_text_list[i])
        value_cell = cells_text_list[i+1].strip()
        
        if label_cell in triggers:
            meta_field = triggers[label_cell]
            meta[meta_field] = value_cell
            i += 2
        else:
            i += 1

# -------------------------------------------------------------------
# 6. Inline meta detection in paragraphs
# -------------------------------------------------------------------
def try_extract_inline_meta(line, meta):
    """
    Check if line matches "Meta Title: Some Value" or "URL: something".
    If found, store in meta and return True.
    """
    # Known triggers
    triggers = {
        "meta title": "Meta Title",
        "title tag": "Meta Title",
        "meta description": "Meta Description",
        "existing url": "URL",
        "url": "URL",
        "h1": "H1"
    }
    # Remove bracketed notes, e.g. (Character limit: 60 max)
    line_no_brackets = re.sub(r"\(Character limit.*?\)", "", line)
    
    if ":" in line_no_brackets:
        parts = line_no_brackets.split(":", 1)
        label = parts[0].strip().lower()
        value = parts[1].strip()
        
        if label in triggers:
            meta[triggers[label]] = value
            return True
    return False

# -------------------------------------------------------------------
# 7. Master "extract_content" function
# -------------------------------------------------------------------
def extract_content(docx_file):
    """
    Reads the docx, extracts meta, headings, and paragraphs.
    Handles:
     - The "SEO Brief" style paragraphs (meta label on one line, value on next).
     - Table-based label->value row parsing.
     - Inline meta e.g. "URL: https://..."
     - Headings "H2: Something"
    """
    doc = docx.Document(docx_file)
    
    meta = {"Meta Title": "", "Meta Description": "", "URL": ""}
    headings = []
    paragraphs = []
    
    # First, parse paragraphs in "SEO brief" style
    # We'll gather them in a list of lines
    doc_paragraph_lines = []
    for para in doc.paragraphs:
        line = para.text.strip()
        if line:
            doc_paragraph_lines.append(line)
    # Now pass to parse function
    parse_paragraphs_for_meta(doc_paragraph_lines, meta, headings, paragraphs)
    
    # Then parse tables (common in V1/V2)
    for table in doc.tables:
        parse_table_for_meta_and_others(table, meta, headings, paragraphs)
    
    return meta, headings, paragraphs

# -------------------------------------------------------------------
# 8. Heading Difference Detection
# -------------------------------------------------------------------
def find_heading_differences(headings_v1, headings_v2):
    """
    Return {"added": set(...), "removed": set(...), "common": set(...)}
    headings_v1, headings_v2 are lists of (H-tag, text).
    """
    set_v1 = set(f"{tag}: {txt}" for tag, txt in headings_v1)
    set_v2 = set(f"{tag}: {txt}" for tag, txt in headings_v2)
    
    added = set_v2 - set_v1
    removed = set_v1 - set_v2
    common = set_v1 & set_v2
    return {"added": added, "removed": removed, "common": common}

# -------------------------------------------------------------------
# 9. AI Summaries for Paragraph-Level Changes
# -------------------------------------------------------------------
def summarize_paragraph_changes(paras_old, paras_new):
    """
    Provide a concise bullet-point or short summary about changes in paragraphs only.
    """
    if not openai.api_key:
        return "OpenAI API key not provided; cannot generate AI summary."
    
    prompt = (
        "You are an expert content analyst. Two versions of content exist. "
        "Focus ONLY on paragraph-level changes (expansions, style shifts, new/removed info). "
        "Do NOT restate heading changes. Provide a bullet-point or short list of major differences.\n\n"
        "VERSION 1 PARAGRAPHS:\n"
        f"{'-'*50}\n{'\n'.join(paras_old)}\n\n"
        "VERSION 2 PARAGRAPHS:\n"
        f"{'-'*50}\n{'\n'.join(paras_new)}\n\n"
        "Now summarize how the paragraph content differs."
    )
    
    response = openai.ChatCompletion.create(
        model="gpt-4",  # or "gpt-3.5-turbo"
        messages=[
            {"role": "system", "content": "You are an unbiased, detail-oriented content analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
    )
    return response["choices"][0]["message"]["content"].strip()

# -------------------------------------------------------------------
# 10. Streamlit UI
# -------------------------------------------------------------------
uploaded_files = st.file_uploader(
    "Upload .docx files (SEO brief, V1, V2, etc.)",
    accept_multiple_files=True,
    type=["docx"]
)

if uploaded_files and len(uploaded_files) >= 2:
    # Parse each file into meta/headings/paragraphs
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
            st.warning("You selected the same file for both. Please choose different versions.")
        else:
            meta_v1, heads_v1, paras_v1 = file_versions[v1]["meta"], file_versions[v1]["headings"], file_versions[v1]["paragraphs"]
            meta_v2, heads_v2, paras_v2 = file_versions[v2]["meta"], file_versions[v2]["headings"], file_versions[v2]["paragraphs"]
            
            # --- Accordions ---
            
            # 1) Metadata
            with st.expander("1) Metadata Changes", expanded=True):
                st.write("Below are the recognized meta fields from each version:")
                for field in ["Meta Title", "Meta Description", "URL"]:
                    old_val = meta_v1.get(field, "")
                    new_val = meta_v2.get(field, "")
                    st.write(f"**{field}**: `{old_val}` → `{new_val}`")
            
            # 2) Heading Comparisons
            with st.expander("2) Heading Comparisons (Side-by-Side)", expanded=True):
                for (h1_tag, h1_txt), (h2_tag, h2_txt) in zip_longest(heads_v1, heads_v2, fillvalue=("", "")):
                    if not (h1_tag or h1_txt or h2_tag or h2_txt):
                        continue
                    st.write(f"- **{h1_tag or '—'}**: `{h1_txt}` → **{h2_tag or '—'}**: `{h2_txt}`")
            
            # 2.1) Separate accordion for added/removed headings
            with st.expander("2.1) Added / Removed Headings", expanded=False):
                diffs = find_heading_differences(heads_v1, heads_v2)
                
                st.subheader("✅ Added Headings")
                if diffs["added"]:
                    for h in diffs["added"]:
                        st.write(f"- {h}")
                else:
                    st.write("*None*")
                
                st.subheader("❌ Removed Headings")
                if diffs["removed"]:
                    for h in diffs["removed"]:
                        st.write(f"- {h}")
                else:
                    st.write("*None*")
            
            # 3) Paragraph-Level Changes (AI)
            with st.expander("3) Paragraph-Level Changes (AI-Powered)", expanded=True):
                if enable_ai and openai_api_key:
                    summary = summarize_paragraph_changes(paras_v1, paras_v2)
                    st.markdown(summary)
                elif enable_ai and not openai_api_key:
                    st.warning("Please provide an OpenAI API key to generate AI summaries.")
                else:
                    st.info("Enable the AI checkbox to see a summary of paragraph-level differences.")
