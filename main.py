import streamlit as st
import docx
import re
import openai
from itertools import zip_longest
from difflib import SequenceMatcher

# -------------------------------------------------------------------
# Streamlit Title & Instructions
# -------------------------------------------------------------------
st.title("📝 SEO Content Draft Comparator")

st.write(
    """
    **Purpose**  
    Compare `.docx` files (e.g., an SEO brief vs. V1 vs. V2) to see:
    - **Meta fields** (Title Tag / Meta Title, Meta Description, URL) 
    - **Headings** (`H1:` - `H6:`) with **unchanged**, **modified**, **added**, and **removed** detection.
    - **Paragraph-level** content changes via optional AI summaries.

    **How to Use**  
    1. **Upload at least two .docx files** (SEO Brief, V1, V2, etc.).  
    2. **Select which two** files to compare from the dropdowns.  
    3. Expand the accordions to see metadata, headings, and added/removed/modified headings.  
    4. (Optional) Provide your **OpenAI API key** and enable AI summarization for a more focused paragraph-level analysis.
    """
)

# -------------------------------------------------------------------
# 1. OpenAI API Key (Optional)
# -------------------------------------------------------------------
openai_api_key = st.text_input("Enter your OpenAI API Key (optional):", type="password")
if openai_api_key:
    openai.api_key = openai_api_key

# Toggle for AI analysis
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
        "h1": "H1",  # In some briefs, the main heading is labeled this way
        "url": "URL"
    }
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        
        clabel = clean_label_text(line)
        if clabel in possible_labels:
            label_key = possible_labels[clabel]  # e.g. "Meta Title"
            # Attempt to get next line as the value
            if i + 1 < len(lines):
                next_line = lines[i+1].strip()
                next_label = clean_label_text(next_line)
                # If the next line is NOT another label, treat it as value
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
        
        # 3) Headings like "H2: Some heading"
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
        # Gather cell texts
        cell_texts = [cell.text.strip() for cell in row.cells]
        # Attempt row-based label->value detection
        parse_meta_fields_from_row(cell_texts, meta)
        
        # Also parse line-by-line
        for ctext in cell_texts:
            for line in ctext.split("\n"):
                line_stripped = line.strip()
                if line_stripped:
                    # Check inline meta
                    if try_extract_inline_meta(line_stripped, meta):
                        continue
                    # Check headings
                    match = re.match(r'^(H[1-6]):\s*(.*)', line_stripped, flags=re.IGNORECASE)
                    if match:
                        headings.append((match.group(1).upper(), match.group(2).strip()))
                    else:
                        paragraphs.append(line_stripped)

# -------------------------------------------------------------------
# 5. Row-based meta detection
# -------------------------------------------------------------------
def parse_meta_fields_from_row(cells_text_list, meta):
    triggers = {
        "meta title": "Meta Title",
        "meta description": "Meta Description",
        "title tag": "Meta Title",
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
    possible_triggers = {
        "meta title": "Meta Title",
        "title tag": "Meta Title",
        "meta description": "Meta Description",
        "existing url": "URL",
        "url": "URL",
        "h1": "H1"
    }
    line_no_brackets = re.sub(r"\(Character limit.*?\)", "", line)
    
    if ":" in line_no_brackets:
        parts = line_no_brackets.split(":", 1)
        label = parts[0].strip().lower()
        value = parts[1].strip()
        if label in possible_triggers:
            meta[possible_triggers[label]] = value
            return True
    return False

# -------------------------------------------------------------------
# 7. Master "extract_content" function
# -------------------------------------------------------------------
def extract_content(docx_file):
    doc = docx.Document(docx_file)
    
    meta = {"Meta Title": "", "Meta Description": "", "URL": ""}
    headings = []
    paragraphs = []
    
    # Parse paragraphs (SEO brief style)
    doc_paragraph_lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    parse_paragraphs_for_meta(doc_paragraph_lines, meta, headings, paragraphs)
    
    # Parse tables (V1/V2 style)
    for table in doc.tables:
        parse_table_for_meta_and_others(table, meta, headings, paragraphs)
    
    return meta, headings, paragraphs

# -------------------------------------------------------------------
# 8. Advanced Heading Comparison (difflib)
# -------------------------------------------------------------------
def analyze_headings(headings_v1, headings_v2, threshold=0.7):
    """
    Returns a dict:
      {
        "unchanged": [(str_v1, str_v2), ...],
        "modified": [(str_v1, str_v2), ...],
        "added": [str_v2, ...],
        "removed": [str_v1, ...]
      }
    - Convert each heading to "H2: Some heading text".
    - For each heading in v2, find best match in v1:
      ratio == 1.0 => unchanged
      ratio >= threshold => modified
      ratio < threshold => added
    - Any unmatched v1 => removed
    """
    v1_strings = [f"{tag}: {txt}" for tag, txt in headings_v1]
    v2_strings = [f"{tag}: {txt}" for tag, txt in headings_v2]
    
    used_v1 = set()
    results = {
        "unchanged": [],
        "modified": [],
        "added": [],
        "removed": []
    }
    
    for heading_v2 in v2_strings:
        best_ratio = 0.0
        best_index = None
        best_str_v1 = None
        
        for i, heading_v1 in enumerate(v1_strings):
            if i in used_v1:
                continue
            ratio = SequenceMatcher(None, heading_v1, heading_v2).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_index = i
                best_str_v1 = heading_v1
        
        if best_ratio == 1.0:
            results["unchanged"].append((best_str_v1, heading_v2))
            used_v1.add(best_index)
        elif best_ratio >= threshold:
            results["modified"].append((best_str_v1, heading_v2))
            used_v1.add(best_index)
        else:
            # Not similar enough => "added"
            results["added"].append(heading_v2)
    
    # Anything in v1 not matched is "removed"
    for i, heading_v1 in enumerate(v1_strings):
        if i not in used_v1:
            results["removed"].append(heading_v1)
    
    return results

# -------------------------------------------------------------------
# 9. AI Summaries for Paragraph-Level Changes
# -------------------------------------------------------------------
def summarize_paragraph_changes(paras_old, paras_new):
    if not openai.api_key:
        return "OpenAI API key not provided; cannot generate AI summary."
    
    prompt = (
        "You are an expert content analyst. Two versions of content exist. "
        "Focus ONLY on paragraph-level changes (expansions, style shifts, new/removed info). "
        "Do NOT restate heading changes. Provide a short list of major differences.\n\n"
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
    "Upload .docx files (SEO Brief, V1, V2, etc.)",
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
            
            # 2) Heading Comparisons (Side-by-Side)
            with st.expander("2) Heading Comparisons (Side-by-Side)", expanded=True):
                st.write("**Line up headings in order:**")
                for (h1_tag, h1_txt), (h2_tag, h2_txt) in zip_longest(heads_v1, heads_v2, fillvalue=("", "")):
                    if not (h1_tag or h1_txt or h2_tag or h2_txt):
                        continue
                    st.write(f"- **{h1_tag or '—'}**: `{h1_txt}` → **{h2_tag or '—'}**: `{h2_txt}`")
            
            # 2.1) Advanced Heading Analysis (unchanged, modified, added, removed)
            with st.expander("2.1) Detailed Subhead Changes (Unchanged/Modified/Added/Removed)", expanded=False):
                st.write("Headings are matched using `difflib.SequenceMatcher` with a default threshold of 0.7.")
                
                heading_diff = analyze_headings(heads_v1, heads_v2, threshold=0.7)
                
                # Unchanged
                if heading_diff["unchanged"]:
                    st.subheader("Unchanged Headings")
                    for old_str, new_str in heading_diff["unchanged"]:
                        st.write(f"- `{old_str}` is the same as `{new_str}`")
                else:
                    st.write("*No unchanged headings.*")
                
                # Modified
                if heading_diff["modified"]:
                    st.subheader("Modified Headings")
                    for old_str, new_str in heading_diff["modified"]:
                        st.write(f"- **Old**: `{old_str}` → **New**: `{new_str}`")
                else:
                    st.write("*No modified headings.*")
                
                # Added
                if heading_diff["added"]:
                    st.subheader("Added Headings")
                    for new_str in heading_diff["added"]:
                        st.write(f"- `{new_str}`")
                else:
                    st.write("*No newly added headings.*")
                
                # Removed
                if heading_diff["removed"]:
                    st.subheader("Removed Headings")
                    for old_str in heading_diff["removed"]:
                        st.write(f"- `{old_str}`")
                else:
                    st.write("*No removed headings.*")
            
            # 3) Paragraph-Level Changes (AI)
            with st.expander("3) Paragraph-Level Changes (AI-Powered)", expanded=True):
                if enable_ai and openai_api_key:
                    summary = summarize_paragraph_changes(paras_v1, paras_v2)
                    st.markdown(summary)
                elif enable_ai and not openai_api_key:
                    st.warning("Please provide an OpenAI API key to generate AI summaries.")
                else:
                    st.info("Enable the AI checkbox to see a summary of paragraph-level differences.")
