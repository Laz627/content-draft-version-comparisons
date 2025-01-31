import streamlit as st
import docx
import re
import openai
from itertools import zip_longest
from difflib import SequenceMatcher

st.title("📝 SEO Content Draft Comparator")

st.markdown(
    """
    **Purpose**  
    Compare `.docx` files (e.g., an SEO brief vs. V1 vs. V2) to see:
    - **Meta fields** (Title Tag / Meta Title, Meta Description, URL)
    - **Headings** (`H1:` - `H6:`) with **unchanged**, **modified**, **added**, and **removed** detection.
    - **Paragraph-level** content changes via optional AI summaries.

    **How to Use**  
    1. **Upload at least two .docx files** (SEO Brief, V1, V2, etc.).  
    2. **Select which two** files to compare.  
    3. Click **Compare Versions**.  
    4. Expand the accordions below to see **Metadata**, **Heading Changes**, and **Paragraph-level** updates.
    """
)

# -----------------------------
# 1. OpenAI API Key (optional)
# -----------------------------
openai_api_key = st.text_input("Enter your OpenAI API Key (optional):", type="password")
if openai_api_key:
    openai.api_key = openai_api_key

enable_ai = st.checkbox("Enable AI-powered paragraph-level analysis")

# -----------------------------
# Helper functions (same as before)
# -----------------------------
def clean_label_text(txt):
    txt = re.sub(r"\(Character limit.*?\)", "", txt)
    txt = txt.replace("(", "").replace(")", "")
    return txt.strip().lower()

def parse_paragraphs_for_meta(lines, meta, headings, paragraphs):
    possible_labels = {
        "meta title": "Meta Title",
        "meta description": "Meta Description",
        "h1": "H1",
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
            label_key = possible_labels[clabel]
            if i + 1 < len(lines):
                next_line = lines[i+1].strip()
                next_label = clean_label_text(next_line)
                if next_label not in possible_labels:
                    meta[label_key] = next_line
                    i += 2
                    continue
            i += 1
            continue
        
        # inline meta
        if try_extract_inline_meta(line, meta):
            i += 1
            continue
        
        # heading "H2: Something"
        match = re.match(r'^(H[1-6]):\s*(.*)', line, flags=re.IGNORECASE)
        if match:
            headings.append((match.group(1).upper(), match.group(2).strip()))
            i += 1
            continue
        
        # otherwise paragraph
        paragraphs.append(line)
        i += 1

def parse_table_for_meta_and_others(table, meta, headings, paragraphs):
    for row in table.rows:
        cell_texts = [cell.text.strip() for cell in row.cells]
        parse_meta_fields_from_row(cell_texts, meta)
        
        for ctext in cell_texts:
            for line in ctext.split("\n"):
                line_stripped = line.strip()
                if line_stripped:
                    if try_extract_inline_meta(line_stripped, meta):
                        continue
                    match = re.match(r'^(H[1-6]):\s*(.*)', line_stripped, flags=re.IGNORECASE)
                    if match:
                        headings.append((match.group(1).upper(), match.group(2).strip()))
                    else:
                        paragraphs.append(line_stripped)

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

def extract_content(docx_file):
    doc = docx.Document(docx_file)
    meta = {"Meta Title": "", "Meta Description": "", "URL": ""}
    headings = []
    paragraphs = []
    
    doc_paragraph_lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    parse_paragraphs_for_meta(doc_paragraph_lines, meta, headings, paragraphs)
    
    for table in doc.tables:
        parse_table_for_meta_and_others(table, meta, headings, paragraphs)
    
    return meta, headings, paragraphs

# difflib-based heading analysis
def analyze_headings(headings_v1, headings_v2, threshold=0.7):
    from difflib import SequenceMatcher
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
            results["added"].append(heading_v2)
    
    # everything not matched in v1 => removed
    for i, heading_v1 in enumerate(v1_strings):
        if i not in used_v1:
            results["removed"].append(heading_v1)
    
    return results

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
        "Provide summaries for all relevant paragraphs where changes occur."
    )
    
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an unbiased, detail-oriented content analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.4,
    )
    return response["choices"][0]["message"]["content"].strip()

# -----------------------------
# Streamlit UI
# -----------------------------
uploaded_files = st.file_uploader(
    "Upload .docx files (SEO Brief, V1, V2, etc.)",
    accept_multiple_files=True,
    type=["docx"]
)

if uploaded_files and len(uploaded_files) >= 2:
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
            
            # -- 1) Metadata
            with st.expander("📄 **1) Metadata Changes**", expanded=False):
                st.markdown("Below are the recognized meta fields from each version:")
                for field in ["Meta Title", "Meta Description", "URL"]:
                    old_val = meta_v1.get(field, "")
                    new_val = meta_v2.get(field, "")
                    st.write(f"**{field}**: `{old_val}` → `{new_val}`")
            
            # -- 2) Heading Comparisons
            with st.expander("🔎 **2) Heading Comparisons (Side-by-Side)**", expanded=False):
                st.markdown("**Line up headings in order:**")
                for (h1_tag, h1_txt), (h2_tag, h2_txt) in zip_longest(heads_v1, heads_v2, fillvalue=("", "")):
                    if not (h1_tag or h1_txt or h2_tag or h2_txt):
                        continue
                    st.write(f"- **{h1_tag or '—'}**: `{h1_txt}` → **{h2_tag or '—'}**: `{h2_txt}`")
            
            # -- 2.1) Detailed Subhead Changes
            with st.expander("✂️ **2.1) Detailed Subhead Changes (Unchanged / Modified / Added / Removed)**", expanded=False):
                st.markdown("Headings are matched using `difflib.SequenceMatcher` with a default threshold of **0.7**.")
                heading_diff = analyze_headings(heads_v1, heads_v2, threshold=0.7)
                
                # Unchanged
                if heading_diff["unchanged"]:
                    st.markdown("### Unchanged Headings")
                    for old_str, new_str in heading_diff["unchanged"]:
                        st.write(f"- `{old_str}` is the same as `{new_str}`")
                else:
                    st.write("*No unchanged headings.*")
                
                # Modified
                if heading_diff["modified"]:
                    st.markdown("### Modified Headings")
                    for old_str, new_str in heading_diff["modified"]:
                        st.write(f"- **Old**: `{old_str}` → **New**: `{new_str}`")
                else:
                    st.write("*No modified headings.*")
                
                # Added
                if heading_diff["added"]:
                    st.markdown("### Added Headings")
                    for new_str in heading_diff["added"]:
                        st.write(f"- `{new_str}`")
                else:
                    st.write("*No newly added headings.*")
                
                # Removed
                if heading_diff["removed"]:
                    st.markdown("### Removed Headings")
                    for old_str in heading_diff["removed"]:
                        st.write(f"- `{old_str}`")
                else:
                    st.write("*No removed headings.*")
            
            # -- 3) Paragraph-Level Changes
            with st.expander("🖊️ **3) Paragraph-Level Changes (AI-Powered)**", expanded=False):
                if enable_ai and openai_api_key:
                    summary = summarize_paragraph_changes(paras_v1, paras_v2)
                    st.markdown(summary)
                elif enable_ai and not openai_api_key:
                    st.warning("Please provide an OpenAI API key to generate AI summaries.")
                else:
                    st.info("Enable the AI checkbox to see a summary of paragraph-level differences.")
