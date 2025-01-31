import streamlit as st
import docx
import re
import openai
from itertools import zip_longest
from difflib import SequenceMatcher

# -------------------------------------------------------------------
# Page Title & Instructions
# -------------------------------------------------------------------
st.title("📝 SEO Content Draft Comparator")

st.markdown(
    """
    ### Overview
    This tool compares different `.docx` files (e.g., SEO Brief, V1, V2) to identify:
    - **Meta fields**: Title Tag / Meta Title, Meta Description, URL  
    - **Headings**: H1 through H6  
    - **Paragraph-level** differences

    ### How to Use
    1. **Upload at least two .docx files** (an SEO brief, V1, V2, etc.).  
    2. **Select which two** you wish to compare from the dropdowns.  
    3. Click on **Compare Versions**.  
    4. **Expand** the sections below:
       - **Metadata Changes**: Quick overview of meta differences (or "No change").  
       - **Heading Comparisons**: Side-by-side listing, plus detailed subhead changes.  
       - **AI Paragraph-Level Analysis** (optional): Summarizes **only** paragraph changes, ignoring headings.  
         - Enable via the "**Enable AI-powered paragraph-level analysis**" checkbox.  
         - Provide an **OpenAI API key** (optional) if you want the AI-generated summary.  
    """,
    unsafe_allow_html=True
)

# -------------------------------------------------------------------
# 1. OpenAI API Key (Optional)
# -------------------------------------------------------------------
openai_api_key = st.text_input("Enter your OpenAI API Key (optional):", type="password")
if openai_api_key:
    openai.api_key = openai_api_key

# Checkbox for AI-based paragraph analysis
enable_ai = st.checkbox("Enable AI-powered paragraph-level analysis (paragraphs only, no heading changes)")

# -------------------------------------------------------------------
# 2. Helper Functions
# -------------------------------------------------------------------

def clean_label_text(txt):
    """
    Remove bracketed notes like (Character limit: 60 max) and extra parentheses.
    Helps in normalizing the label text for meta fields.
    """
    txt = re.sub(r"\(Character limit.*?\)", "", txt)
    txt = txt.replace("(", "").replace(")", "")
    return txt.strip().lower()

def parse_paragraphs_for_meta(lines, meta, headings, paragraphs):
    """
    Identify meta fields (Meta Title, Meta Description, etc.), headings (H2: SomeHeading),
    or treat the rest as paragraphs.  

    - If we see a known label (e.g., "Meta Title"), we store the next line as its value (if not also a label).
    - If we see something like "Meta Title: Some Title" inline, we capture that too.
    - If we see "H2: Why Bifold Doors?", we add that to 'headings'.
    - Else it's appended to 'paragraphs'.
    """
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
            # It's a direct label (e.g., "Meta Title")
            label_key = possible_labels[clabel]
            # Attempt to get the next line as the value
            if i + 1 < len(lines):
                next_line = lines[i+1].strip()
                next_label = clean_label_text(next_line)
                if next_label not in possible_labels:
                    meta[label_key] = next_line
                    i += 2
                    continue
            i += 1
            continue
        
        # Inline meta detection (e.g., "Meta Title: Sliding Door Alternatives")
        if try_extract_inline_meta(line, meta):
            i += 1
            continue
        
        # Headings: "H2: Some heading"
        match = re.match(r'^(H[1-6]):\s*(.*)', line, flags=re.IGNORECASE)
        if match:
            headings.append((match.group(1).upper(), match.group(2).strip()))
            i += 1
            continue
        
        # If none of the above => treat as a paragraph
        paragraphs.append(line)
        i += 1

def try_extract_inline_meta(line, meta):
    """
    Checks if the line contains an inline meta definition like
    "Meta Title: Some Title" or "URL: https://..."
    If so, update 'meta' dict accordingly and return True.
    """
    triggers = {
        "meta title": "Meta Title",
        "title tag": "Meta Title",
        "meta description": "Meta Description",
        "existing url": "URL",
        "url": "URL",
        "h1": "H1"
    }
    # Remove bracketed notes
    line_no_brackets = re.sub(r"\(Character limit.*?\)", "", line)
    
    if ":" in line_no_brackets:
        parts = line_no_brackets.split(":", 1)
        label = parts[0].strip().lower()
        value = parts[1].strip()
        if label in triggers:
            meta[triggers[label]] = value
            return True
    return False

def parse_table_for_meta_and_others(table, meta, headings, paragraphs):
    """
    In docx tables, parse row by row:
    - Attempt label->value extraction (for meta fields).
    - Look for "H2: Something" headings.
    - Else treat as paragraphs.
    """
    for row in table.rows:
        cell_texts = [cell.text.strip() for cell in row.cells]
        parse_meta_fields_from_row(cell_texts, meta)
        
        for ctext in cell_texts:
            for line in ctext.split("\n"):
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                if try_extract_inline_meta(line_stripped, meta):
                    continue
                # Check headings
                match = re.match(r'^(H[1-6]):\s*(.*)', line_stripped, flags=re.IGNORECASE)
                if match:
                    headings.append((match.group(1).upper(), match.group(2).strip()))
                else:
                    paragraphs.append(line_stripped)

def parse_meta_fields_from_row(cells_text_list, meta):
    """
    If a table row has label->value pairs (e.g., "Meta Title", "My Title"),
    store them in 'meta'.
    """
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

def extract_content(docx_file):
    """
    Main function that loads the .docx file and extracts:
    - meta (dict)
    - headings (list of (H2, "some heading text"))
    - paragraphs (list of strings)
    """
    doc = docx.Document(docx_file)
    meta = {"Meta Title": "", "Meta Description": "", "URL": ""}
    headings = []
    paragraphs = []
    
    # Parse paragraphs in the doc body
    doc_paragraph_lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    parse_paragraphs_for_meta(doc_paragraph_lines, meta, headings, paragraphs)
    
    # Parse any tables (common in V1/V2)
    for table in doc.tables:
        parse_table_for_meta_and_others(table, meta, headings, paragraphs)
    
    return meta, headings, paragraphs

# -------------------------------------------------------------------
# 3. Group Paragraphs Under Headings
# -------------------------------------------------------------------
def group_content_by_headings(headings, paragraphs):
    """
    Returns a list of sections, each structured as:
      { "heading": "H2: Some Title" or None, "paragraphs": [...paragraphs...] }

    Because we separated out headings and paragraphs, we can't
    perfectly reconstruct the doc's original ordering. As a simpler approach:
    - We create one "section" per heading (with empty paragraphs).
    - Then one final "section" for all leftover paragraphs with heading=None.
    """
    sections = []
    # Create a section for each heading
    for h in headings:
        heading_text = f"{h[0]}: {h[1]}"
        sections.append({
            "heading": heading_text,
            "paragraphs": []
        })
    # All paragraphs lumped into a "no heading" section
    if paragraphs:
        sections.append({
            "heading": None,
            "paragraphs": paragraphs
        })
    return sections

# -------------------------------------------------------------------
# 4. Compare Sections with AI (Ignoring Heading Changes)
# -------------------------------------------------------------------
def compare_sections_with_ai(sections_old, sections_new):
    """
    Build a prompt that focuses ONLY on changed paragraphs within
    each grouped 'section.' If a heading is new or removed, mention it,
    but for the final user request we won't highlight heading changes
    in the AI output— or we can remove that part of the instructions
    to truly ignore subhead changes.
    """
    if not openai.api_key:
        return "OpenAI API key not provided; cannot generate AI summary."
    
    def format_sections(version_name, sections):
        out = [f"**{version_name}**:"]
        for i, sec in enumerate(sections):
            heading_label = sec["heading"] if sec["heading"] else "No Heading"
            out.append(f"- Section {i+1}, Heading: {heading_label}")
            for j, paragraph in enumerate(sec["paragraphs"]):
                out.append(f"  Paragraph {j+1}: {paragraph}")
        return "\n".join(out)
    
    text_old = format_sections("Version 1", sections_old)
    text_new = format_sections("Version 2", sections_new)
    
    # Instruction to ignore heading changes in the summary
    prompt = (
        "You are an expert content analyst. Two versions of content are grouped by headings, "
        "but we want to focus ONLY on paragraph-level changes. Ignore heading changes or subhead differences. "
        "Omit sections that are identical in both versions. "
        "For changed paragraphs, provide bullet points describing expansions, deletions, or new info.\n\n"
        f"{text_old}\n\n"
        f"{text_new}\n\n"
        "Now summarize the paragraph changes only (ignore heading changes). "
        "Use bullet points, skip identical paragraphs, and be concise."
    )
    
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an unbiased, detail-oriented content analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
    )
    return response["choices"][0]["message"]["content"].strip()

# -------------------------------------------------------------------
# 5. Advanced Headings Analysis (difflib)
# -------------------------------------------------------------------
def analyze_headings(headings_v1, headings_v2, threshold=0.7):
    """
    Return a dict with:
      { "unchanged": [(str_v1, str_v2), ...],
        "modified":  [...],
        "added":     [...],
        "removed":   [...] }
    
    We unify each heading as "H2: Some heading text" for comparison.
    If ratio == 1.0 => unchanged
    elif ratio >= threshold => modified
    else => new/added
    Then anything in V1 not matched => removed.
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
            results["added"].append(heading_v2)
    
    # Anything left in v1 => removed
    for i, heading_v1 in enumerate(v1_strings):
        if i not in used_v1:
            results["removed"].append(heading_v1)
    
    return results

# -------------------------------------------------------------------
# Streamlit UI
# -------------------------------------------------------------------
uploaded_files = st.file_uploader(
    "Upload .docx files (e.g., SEO Brief, V1, V2).",
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
    
    # Step for user to pick which two to compare
    v1 = st.selectbox("Select the FIRST version to compare:", versions)
    v2 = st.selectbox("Select the SECOND version to compare:", versions, 
                      index=min(1, len(versions)-1))
    
    # Button to trigger comparison
    if st.button("Compare Versions"):
        if v1 == v2:
            st.warning("You selected the same file for both. Please choose different versions.")
        else:
            meta_v1, heads_v1, paras_v1 = file_versions[v1]["meta"], file_versions[v1]["headings"], file_versions[v1]["paragraphs"]
            meta_v2, heads_v2, paras_v2 = file_versions[v2]["meta"], file_versions[v2]["headings"], file_versions[v2]["paragraphs"]
            
            # 1) Metadata
            with st.expander("📄 **1) Metadata Changes**", expanded=False):
                st.markdown("A quick overview of the meta field differences or 'No change' if identical.")
                fields = ["Meta Title", "Meta Description", "URL"]
                any_meta_changes = False
                for fld in fields:
                    old_val = meta_v1.get(fld, "")
                    new_val = meta_v2.get(fld, "")
                    if old_val == new_val:
                        st.write(f"**{fld}:** No change.")
                    else:
                        any_meta_changes = True
                        st.write(f"**{fld}:** `{old_val}` → `{new_val}`")
                if not any_meta_changes:
                    st.write("No meta fields were changed between these versions.")
            
            # 2) Heading Comparisons (Side-by-Side)
            with st.expander("🔎 **2) Heading Comparisons (Side-by-Side)**", expanded=False):
                st.markdown("**Here are the headings, lined up in order for Version 1 vs. Version 2:**")
                for (h1_tag, h1_txt), (h2_tag, h2_txt) in zip_longest(heads_v1, heads_v2, fillvalue=("", "")):
                    if not (h1_tag or h1_txt or h2_tag or h2_txt):
                        continue
                    st.write(f"- **{h1_tag or '—'}**: `{h1_txt}` → **{h2_tag or '—'}**: `{h2_txt}`")
            
            # 2.1) Detailed Subhead Changes
            with st.expander("✂️ **2.1) Detailed Subhead Changes**", expanded=False):
                heading_diff = analyze_headings(heads_v1, heads_v2, threshold=0.7)
                
                cnt_unchanged = len(heading_diff["unchanged"])
                cnt_modified  = len(heading_diff["modified"])
                cnt_added     = len(heading_diff["added"])
                cnt_removed   = len(heading_diff["removed"])
                
                st.markdown(f"""
                **Summary of Heading Changes**  
                - **Unchanged**: `{cnt_unchanged}`  
                - **Modified**: `{cnt_modified}`  
                - **Added**: `{cnt_added}`  
                - **Removed**: `{cnt_removed}`  
                """)
                
                st.info("Headings matched via `difflib.SequenceMatcher` (threshold=0.7).")
                
                # We only show the details for modified, added, removed; unchanged is just a count
                st.markdown("### ⚠️ Modified Headings")
                if heading_diff["modified"]:
                    for old_h, new_h in heading_diff["modified"]:
                        st.write(f"⚠️ **Old**: `{old_h}` → **New**: `{new_h}`")
                else:
                    st.write("*No modified headings.*")
                
                st.markdown("### ➕ Added Headings")
                if heading_diff["added"]:
                    for new_str in heading_diff["added"]:
                        st.write(f"➕ `{new_str}`")
                else:
                    st.write("*No newly added headings.*")
                
                st.markdown("### ❌ Removed Headings")
                if heading_diff["removed"]:
                    for old_str in heading_diff["removed"]:
                        st.write(f"❌ `{old_str}`")
                else:
                    st.write("*No removed headings.*")
            
            # 3) Paragraph-Level Changes (AI, ignoring heading changes)
            with st.expander("🖊️ **3) Paragraph-Level Changes (AI-Powered)**", expanded=False):
                if enable_ai and openai_api_key:
                    # Group paragraphs by heading for each version
                    sections_v1 = group_content_by_headings(heads_v1, paras_v1)
                    sections_v2 = group_content_by_headings(heads_v2, paras_v2)
                    
                    # Compare sections with AI, ignoring heading differences
                    ai_output = compare_sections_with_ai(sections_v1, sections_v2)
                    st.markdown(ai_output)
                elif enable_ai and not openai_api_key:
                    st.warning("Please provide an OpenAI API key above to generate AI summaries.")
                else:
                    st.info("Enable the AI checkbox to see bullet-pointed paragraph-level differences (omitting identical paragraphs and ignoring heading changes).")
