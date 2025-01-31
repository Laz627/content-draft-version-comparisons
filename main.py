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
    **Purpose**  
    Compare `.docx` files (e.g., an SEO brief vs. V1 vs. V2) to see:
    - **Meta fields** (Title Tag / Meta Title, Meta Description, URL)
    - **Headings** (`H1:` - `H6:`) with **unchanged**, **modified**, **added**, and **removed** detection
    - **Paragraph-level** content changes via optional AI summaries **grouped by subhead** (omitting unchanged sections).
    
    **How to Use**  
    1. **Upload at least two .docx files** (SEO Brief, V1, V2, etc.).  
    2. **Select which two** files to compare.  
    3. Click **Compare Versions**.  
    4. Expand each section to see **Metadata**, **Heading Changes**, and a **Deeper AI Analysis** of paragraphs, **only** mentioning changed sections.
    """
)

# -------------------------------------------------------------------
# 1. OpenAI API Key (Optional)
# -------------------------------------------------------------------
openai_api_key = st.text_input("Enter your OpenAI API Key (optional):", type="password")
if openai_api_key:
    openai.api_key = openai_api_key

# Checkbox for AI-based paragraph analysis
enable_ai = st.checkbox("Enable AI-powered paragraph-level analysis (grouped by headings)")

# -------------------------------------------------------------------
# 2. Helper Functions
# -------------------------------------------------------------------

def clean_label_text(txt):
    """Remove bracketed notes like (Character limit: 60 max) and extra parentheses."""
    txt = re.sub(r"\(Character limit.*?\)", "", txt)
    txt = txt.replace("(", "").replace(")", "")
    return txt.strip().lower()


def parse_paragraphs_for_meta(lines, meta, headings, paragraphs):
    """
    Identify meta fields (Meta Title, Meta Description, etc.),
    headings (e.g. H2: Some Heading), or treat the rest as paragraphs.
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
        # If line is a known label, store next line as its value
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
        
        # If line might be inline meta (e.g. "Meta Title: Some Title")
        if try_extract_inline_meta(line, meta):
            i += 1
            continue
        
        # If line is a heading "H2: Something"
        match = re.match(r'^(H[1-6]):\s*(.*)', line, flags=re.IGNORECASE)
        if match:
            headings.append((match.group(1).upper(), match.group(2).strip()))
            i += 1
            continue
        
        # Otherwise it's a paragraph
        paragraphs.append(line)
        i += 1


def try_extract_inline_meta(line, meta):
    """
    Checks if 'line' has something like "Meta Title: Some Title"
    or "URL: https://..." inline. If so, store in meta.
    """
    triggers = {
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
        if label in triggers:
            meta[triggers[label]] = value
            return True
    
    return False


def parse_table_for_meta_and_others(table, meta, headings, paragraphs):
    """
    In docx tables, parse row by row, detecting label->value cells for meta,
    as well as lines matching "H2: Something" for headings.
    """
    for row in table.rows:
        cell_texts = [cell.text.strip() for cell in row.cells]
        parse_meta_fields_from_row(cell_texts, meta)
        
        for ctext in cell_texts:
            for line in ctext.split("\n"):
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                # inline meta?
                if try_extract_inline_meta(line_stripped, meta):
                    continue
                # heading?
                match = re.match(r'^(H[1-6]):\s*(.*)', line_stripped, flags=re.IGNORECASE)
                if match:
                    headings.append((match.group(1).upper(), match.group(2).strip()))
                else:
                    paragraphs.append(line_stripped)


def parse_meta_fields_from_row(cells_text_list, meta):
    """
    If a table row has label->value pairs (e.g. "Meta Title", "My Title..."),
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
    Main function that loads the .docx, extracting meta, headings, and paragraphs.
    """
    doc = docx.Document(docx_file)
    meta = {"Meta Title": "", "Meta Description": "", "URL": ""}
    headings = []
    paragraphs = []
    
    # Gather paragraphs from doc (minus blank lines)
    doc_paragraph_lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    parse_paragraphs_for_meta(doc_paragraph_lines, meta, headings, paragraphs)
    
    # Then parse each table
    for table in doc.tables:
        parse_table_for_meta_and_others(table, meta, headings, paragraphs)
    
    return meta, headings, paragraphs


# -------------------------------------------------------------------
# 3. Group Paragraphs Under Their Closest Heading
# -------------------------------------------------------------------
def group_content_by_headings(headings, paragraphs):
    """
    Returns a list of sections, each with:
      {
        "heading": "H2: Title" (or None),
        "paragraphs": [para1, para2, ...]
      }
    
    Since the code originally splits headings[] and paragraphs[] separately,
    we can't perfectly match them in order. As a minimal approach, we:
    1) Create one "section" per heading with no paragraphs.
    2) Make a final section for all paragraphs with heading=None.

    For a more accurate assignment, you'd parse the .docx in a single pass
    and store paragraphs immediately under the heading that precedes them.
    """
    sections = []
    # Create a section for each heading (with no paragraphs)
    for h in headings:
        heading_text = f"{h[0]}: {h[1]}"
        sections.append({"heading": heading_text, "paragraphs": []})
    
    # Then add one final "unheaded" section containing all paragraphs
    if paragraphs:
        sections.append({"heading": None, "paragraphs": paragraphs})
    
    return sections


# -------------------------------------------------------------------
# 4. Compare Sections in AI Prompt (Only mention changed ones)
# -------------------------------------------------------------------
def compare_sections_with_ai(sections_old, sections_new):
    """
    Sends the grouped sections to OpenAI.
    Tells it to ONLY mention headings/paragraphs that changed,
    label each paragraph with the heading, etc.
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
    
    prompt = (
        "You are an expert content analyst. Two versions of content are grouped by heading. "
        "Only mention sections (headings) that changed. If a heading is new or removed, mention it. "
        "If the paragraphs under a heading changed, mention them. If a section is identical in both versions, omit it. "
        "For changed sections, identify the heading (if any) and describe the changes in paragraphs.\n\n"
        f"{text_old}\n\n"
        f"{text_new}\n\n"
        "Provide a concise summary of all changes in headings/paragraphs, only for those that differ. "
        "Omit any sections that are identical."
    )
    
    # Use GPT-4 (or "gpt-3.5-turbo" if needed)
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an unbiased, detail-oriented content analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
    )
    return response["choices"][0]["message"]["content"].strip()


# -------------------------------------------------------------------
# 5. Headings Analysis (difflib) from existing code
# -------------------------------------------------------------------
def analyze_headings(headings_v1, headings_v2, threshold=0.7):
    """
    Return { "unchanged": [...], "modified": [...], "added": [...], "removed": [...] }.
    Each item is a string like "H2: Some heading".
    We'll ignore listing unchanged headings in detail if the user wants less clutter.
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
            # Unchanged
            results["unchanged"].append((best_str_v1, heading_v2))
            used_v1.add(best_index)
        elif best_ratio >= threshold:
            # Modified
            results["modified"].append((best_str_v1, heading_v2))
            used_v1.add(best_index)
        else:
            # If below threshold => "added"
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
    "Upload .docx files (SEO Brief, V1, V2, etc.)",
    accept_multiple_files=True,
    type=["docx"]
)

if uploaded_files and len(uploaded_files) >= 2:
    # Parse each file into (meta, headings, paragraphs)
    file_versions = {}
    for f in uploaded_files:
        meta, headings, paragraphs = extract_content(f)
        file_versions[f.name] = {
            "meta": meta,
            "headings": headings,
            "paragraphs": paragraphs
        }
    
    versions = list(file_versions.keys())
    
    # Let user pick which two .docx files to compare
    v1 = st.selectbox("Select the FIRST version to compare:", versions)
    v2 = st.selectbox("Select the SECOND version to compare:", versions, 
                      index=min(1, len(versions)-1))
    
    if st.button("Compare Versions"):
        if v1 == v2:
            st.warning("You selected the same file for both. Please choose different versions.")
        else:
            meta_v1, heads_v1, paras_v1 = file_versions[v1]["meta"], file_versions[v1]["headings"], file_versions[v1]["paragraphs"]
            meta_v2, heads_v2, paras_v2 = file_versions[v2]["meta"], file_versions[v2]["headings"], file_versions[v2]["paragraphs"]
            
            # --- (1) Metadata ---
            with st.expander("📄 **1) Metadata Changes**", expanded=False):
                st.markdown("Here’s a quick at-a-glance look at meta field differences:")
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
            
            # --- (2) Heading Comparisons Side-by-Side ---
            with st.expander("🔎 **2) Heading Comparisons (Side-by-Side)**", expanded=False):
                st.markdown("**Line up headings in the order they appeared:**")
                for (h1_tag, h1_txt), (h2_tag, h2_txt) in zip_longest(heads_v1, heads_v2, fillvalue=("", "")):
                    if not (h1_tag or h1_txt or h2_tag or h2_txt):
                        continue
                    st.write(f"- **{h1_tag or '—'}**: `{h1_txt}` → **{h2_tag or '—'}**: `{h2_txt}`")
            
            # --- (2.1) Detailed Subhead Changes ---
            with st.expander("✂️ **2.1) Detailed Subhead Changes**", expanded=False):
                diffs = analyze_headings(heads_v1, heads_v2, threshold=0.7)
                
                cnt_unchanged = len(diffs["unchanged"])
                cnt_modified  = len(diffs["modified"])
                cnt_added     = len(diffs["added"])
                cnt_removed   = len(diffs["removed"])
                
                st.markdown(f"""
                **Summary of Heading Changes**  
                - **Unchanged**: `{cnt_unchanged}`  
                - **Modified**: `{cnt_modified}`  
                - **Added**: `{cnt_added}`  
                - **Removed**: `{cnt_removed}`  
                """)
                
                st.info("Headings matched via `difflib.SequenceMatcher` (threshold=0.7).")
                
                # Only show "unchanged" as a count (do not list them all)
                
                # Modified
                st.markdown("### ⚠️ Modified Headings")
                if diffs["modified"]:
                    for old_h, new_h in diffs["modified"]:
                        st.write(f"⚠️ **Old**: `{old_h}` → **New**: `{new_h}`")
                else:
                    st.write("*No modified headings.*")
                
                # Added
                st.markdown("### ➕ Added Headings")
                if diffs["added"]:
                    for new_str in diffs["added"]:
                        st.write(f"➕ `{new_str}`")
                else:
                    st.write("*No newly added headings.*")
                
                # Removed
                st.markdown("### ❌ Removed Headings")
                if diffs["removed"]:
                    for old_str in diffs["removed"]:
                        st.write(f"❌ `{old_str}`")
                else:
                    st.write("*No removed headings.*")
            
            # --- (3) Paragraph-Level Changes (Grouped by Heading, Only Mention Changes) ---
            with st.expander("🖊️ **3) Paragraph-Level Changes (AI-Powered)**", expanded=False):
                if enable_ai and openai_api_key:
                    # Group paragraphs by heading for each version
                    sections_v1 = group_content_by_headings(heads_v1, paras_v1)
                    sections_v2 = group_content_by_headings(heads_v2, paras_v2)
                    
                    # Compare these sections with AI, ignoring identical
                    ai_output = compare_sections_with_ai(sections_v1, sections_v2)
                    st.markdown(ai_output)
                elif enable_ai and not openai_api_key:
                    st.warning("Please provide an OpenAI API key above to generate AI summaries.")
                else:
                    st.info("Enable the AI checkbox to see a grouped summary of paragraph-level differences (omitting unchanged).")
