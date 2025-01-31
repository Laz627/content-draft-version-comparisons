import streamlit as st
import docx
import re
import openai
from itertools import zip_longest

# -----------------------------
# Streamlit Title
# -----------------------------
st.title("📝 SEO Content Draft Comparator")

st.write(
    """
    This tool compares two `.docx` files for:
    - **Meta fields** (Title Tag, Meta Description, Existing URL, etc.)
    - **Headings** (`H1:` through `H6:`)
    - **Paragraph-level** changes (optional AI summarization).
    
    **Notes**:
    - "Title Tag" is stored internally as "Meta Title".
    - "Existing URL" is stored as "URL".
    - The script searches both paragraphs and table cells.
    """
)

# -----------------------------
# 1. OpenAI API Key (Optional)
# -----------------------------
openai_api_key = st.text_input("Enter your OpenAI API Key (optional):", type="password")
if openai_api_key:
    openai.api_key = openai_api_key

# -----------------------------
# 2. Collect lines from paragraphs or table cells
# -----------------------------
def collect_all_lines(doc):
    """
    Returns a list of text lines from:
      - doc.paragraphs
      - doc.tables -> rows -> cells -> cell.paragraphs
    """
    lines = []
    
    # Paragraphs
    for para in doc.paragraphs:
        txt = para.text.strip()
        if txt:
            lines.append(txt)
    
    # Tables
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for cpara in cell.paragraphs:
                    txt = cpara.text.strip()
                    if txt:
                        lines.append(txt)
    
    return lines

# -----------------------------
# 3. Parse lines to extract meta fields, headings, paragraphs
# -----------------------------
def parse_lines_into_content(lines):
    """
    Takes in a list of lines. 
    Returns:
      meta (dict)  -> e.g. {"Meta Title": "", "Meta Description": "", "URL": ""}
      headings (list of (H-tag, text))
      paragraphs (list of str)
    
    Logic:
      - If line is "Title Tag", store next line as meta["Meta Title"] (if it exists)
      - If line is "Meta Description", store next line as meta["Meta Description"]
      - If line is "Existing URL", store next line as meta["URL"]
      - Also check for lines that START with these words, for fallback.
      - For headings, match "H2: Something"
      - Everything else = paragraphs
    """
    meta = {"Meta Title": "", "Meta Description": "", "URL": ""}
    headings = []
    paragraphs = []
    
    # We'll do a two-pass approach:
    # Pass #1: detect lines like "Title Tag" or "Meta Description" or "Existing URL"
    #          if found, store next line. We'll mark them so we don't re-parse them as paragraphs.
    
    used_indices = set()  # track which lines we've consumed in these meta extractions
    # we can unify them with a known set of possible triggers
    triggers = {
        "title tag": "Meta Title",
        "meta title": "Meta Title",
        "meta description": "Meta Description",
        "existing url": "URL",
        "url": "URL"
    }
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        line_lower = line.lower()
        
        if line_lower in triggers:
            field_name = triggers[line_lower]  # e.g. "Meta Title" or "URL"
            used_indices.add(i)
            # see if next line has the value
            if i + 1 < len(lines):
                potential_value = lines[i+1].strip()
                # only store if the next line is not also a recognized trigger
                # e.g. "Meta Description"
                if potential_value.lower() not in triggers:
                    meta[field_name] = potential_value
                    used_indices.add(i+1)
                    i += 2
                    continue
        i += 1
    
    # Pass #2: interpret lines that haven't been used for meta extractions 
    for idx, line in enumerate(lines):
        if idx in used_indices:
            continue
        
        # Check if line starts with triggers in the same line (like "Title Tag: Some Title")
        line_lower = line.lower()
        matched_trigger = None
        for trigger_key, meta_key in triggers.items():
            # if line_lower starts with "title tag:"
            if line_lower.startswith(trigger_key + ":"):
                matched_trigger = meta_key
                break
        
        if matched_trigger:
            # parse out the remainder as the meta value
            remainder = re.split(r':\s*', line, maxsplit=1)
            if len(remainder) == 2:
                meta[matched_trigger] = remainder[1].strip()
            continue
        
        # Next, check headings "H2: Some heading"
        match = re.match(r'^(H[1-6]):\s*(.*)', line)
        if match:
            headings.append((match.group(1), match.group(2)))
        else:
            paragraphs.append(line)
    
    return meta, headings, paragraphs

def extract_content(docx_file):
    """
    Main function that reads the .docx file,
    collects all lines, and parses them into meta/headings/paragraphs.
    """
    doc = docx.Document(docx_file)
    lines = collect_all_lines(doc)
    meta, headings, paragraphs = parse_lines_into_content(lines)
    return meta, headings, paragraphs

# -----------------------------
# 4. Compare headings: added / removed
# -----------------------------
def find_heading_differences(headings_v1, headings_v2):
    """
    headings_v1, headings_v2 are lists of (tag, text) e.g. [("H2","Some heading")]
    We'll unify them as strings "H2: Some heading" to do set diff.
    """
    set_v1 = set(f"{tag}: {text}" for tag, text in headings_v1)
    set_v2 = set(f"{tag}: {text}" for tag, text in headings_v2)
    
    added = set_v2 - set_v1
    removed = set_v1 - set_v2
    common = set_v1 & set_v2
    
    return {"added": added, "removed": removed, "common": common}

# -----------------------------
# 5. AI Summarization (Paragraph-Focused)
# -----------------------------
def generate_ai_paragraph_summary(paragraphs_old, paragraphs_new):
    """
    Calls OpenAI to produce a bullet-point style summary focusing
    on paragraph-level changes (NOT headings).
    """
    if not openai.api_key:
        return "OpenAI API key not provided; cannot generate AI summary."
    
    prompt = (
        "You are an expert content analyst. Two versions of content exist. "
        "Focus ONLY on paragraph-level changes, style shifts, emphasis, or new/removed information. "
        "Do NOT restate heading differences. Provide a concise bullet-point list of the key paragraph changes.\n\n"
        "VERSION 1 PARAGRAPHS:\n"
        f"{'-'*50}\n{'\n'.join(paragraphs_old)}\n\n"
        "VERSION 2 PARAGRAPHS:\n"
        f"{'-'*50}\n{'\n'.join(paragraphs_new)}\n\n"
        "Now summarize how the paragraph content has changed between the two versions, focusing on style, tone, and details introduced or removed."
    )
    
    response = openai.ChatCompletion.create(
        model="gpt-4",  # or gpt-3.5-turbo
        messages=[
            {"role": "system", "content": "You are an unbiased, detail-oriented content analyst."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
    )
    return response["choices"][0]["message"]["content"].strip()

# -----------------------------
# 6. Streamlit UI
# -----------------------------
enable_ai = st.checkbox("Enable AI-powered paragraph-level analysis")

uploaded_files = st.file_uploader(
    "Upload .docx files (SEO brief, V1, V2, etc.)", 
    accept_multiple_files=True, 
    type=["docx"]
)

if uploaded_files and len(uploaded_files) >= 2:
    file_versions = {}
    for file in uploaded_files:
        meta, headings, paragraphs = extract_content(file)
        file_versions[file.name] = {
            "meta": meta,
            "headings": headings,
            "paragraphs": paragraphs
        }
    
    versions = list(file_versions.keys())
    v1 = st.selectbox("Select the first version to compare:", versions)
    v2 = st.selectbox("Select the second version to compare:", versions, 
                      index=1 if len(versions) > 1 else 0)
    
    if st.button("Compare Versions"):
        if v1 == v2:
            st.warning("You selected the same file for both versions. Please select different versions.")
        else:
            # Retrieve data
            meta_v1, headings_v1, paragraphs_v1 = file_versions[v1]["meta"], file_versions[v1]["headings"], file_versions[v1]["paragraphs"]
            meta_v2, headings_v2, paragraphs_v2 = file_versions[v2]["meta"], file_versions[v2]["headings"], file_versions[v2]["paragraphs"]
            
            # ------------------
            # Metadata
            # ------------------
            st.subheader("🔍 Metadata Changes")
            # Show the known fields in meta
            # If you have more fields, just add them to the dict or parse function
            fields_to_show = ["Meta Title", "Meta Description", "URL"]
            
            for f in fields_to_show:
                old_val = meta_v1.get(f, "")
                new_val = meta_v2.get(f, "")
                # If both are blank, it might mean not found in either doc
                st.write(f"**{f}**: `{old_val}` → `{new_val}`")
            
            # ------------------
            # Heading Comparison
            # ------------------
            st.subheader("📌 Heading Changes (Side-by-Side)")

            # We show them in parallel for quick reference
            for (h1_tag, h1_txt), (h2_tag, h2_txt) in zip_longest(headings_v1, headings_v2, fillvalue=("", "")):
                if not (h1_tag or h1_txt or h2_tag or h2_txt):
                    continue
                st.write(f"- **{h1_tag or '—'}**: `{h1_txt}` → **{h2_tag or '—'}**: `{h2_txt}`")
            
            # Identify added / removed
            heading_diffs = find_heading_differences(headings_v1, headings_v2)
            
            st.subheader("✅ Added vs. ❌ Removed Headings")
            if heading_diffs["added"]:
                st.write("**Added**:")
                for h in heading_diffs["added"]:
                    st.write(f"- {h}")
            else:
                st.write("**No newly added headings**.")
            
            if heading_diffs["removed"]:
                st.write("**Removed**:")
                for h in heading_diffs["removed"]:
                    st.write(f"- {h}")
            else:
                st.write("**No removed headings**.")
            
            # ------------------
            # AI Summaries (Paragraph-Level)
            # ------------------
            if enable_ai:
                st.subheader("🤖 AI-Powered Paragraph Changes")
                if openai_api_key:
                    # Summarize how paragraphs changed, ignoring headings
                    summary = generate_ai_paragraph_summary(paragraphs_v1, paragraphs_v2)
                    st.write(summary)
                else:
                    st.warning("Please enter a valid OpenAI API key to generate the AI summary.")
            else:
                st.info("Enable AI summarization above to see a bullet-point overview of paragraph changes.")
