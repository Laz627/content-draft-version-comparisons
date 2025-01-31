import streamlit as st
import docx
import re
import openai
from itertools import zip_longest

st.title("📝 SEO Content Draft Comparator")
st.write(
    "Upload different versions of your content to analyze heading, metadata, and paragraph changes.\n"
    "**Note**: If you enable AI-powered summarization, you will need an OpenAI API key."
)

# -----------------------------
# 1. User OpenAI API Key
# -----------------------------
openai_api_key = st.text_input("Enter your OpenAI API Key (optional):", type="password")
if openai_api_key:
    openai.api_key = openai_api_key

# -----------------------------
# 2. Helper function to process text lines
#    so we can extract meta fields & headings
# -----------------------------
def process_text_line(text_line, meta, headings, paragraphs):
    """
    Check the given text_line for known meta fields or headings.
    Anything not recognized as a meta field or heading is appended to 'paragraphs'.
    """
    if not text_line:
        return
    
    line_lower = text_line.lower()

    # Extract known meta fields
    if line_lower.startswith("meta title"):
        meta["Meta Title"] = text_line.split("meta title", 1)[-1].strip(": ").strip()
    elif line_lower.startswith("h1"):
        meta["H1"] = text_line.split("h1", 1)[-1].strip(": ").strip()
    elif line_lower.startswith("url"):
        meta["URL"] = text_line.split("url", 1)[-1].strip(": ").strip()
    # If you have additional fields like "Meta Description", add here:
    # elif line_lower.startswith("meta description"):
    #     meta["Meta Description"] = text_line.split("meta description", 1)[-1].strip(": ").strip()

    # Identify headings in the form "H2: Some Heading"
    # This pattern captures headings like "H1: Title" or "H3: Subtopic"
    match = re.match(r'^(H[1-6]):\s*(.*)', text_line)
    if match:
        heading_tag = match.group(1).strip()
        heading_text = match.group(2).strip()
        headings.append((heading_tag, heading_text))
    else:
        # Otherwise, treat it as a paragraph
        paragraphs.append(text_line)

# -----------------------------
# 3. Main extraction function
#    - pulls content from paragraphs & table cells
# -----------------------------
def extract_content(docx_file):
    """
    Returns:
      meta (dict): e.g. {"Meta Title": "", "H1": "", "URL": ""}
      headings (list of (tag, text)): e.g. [("H2", "Some heading")]
      paragraphs (list of str)
    """
    doc = docx.Document(docx_file)
    headings = []
    meta = {"Meta Title": "", "H1": "", "URL": ""}  # Add keys as needed
    paragraphs = []
    
    # Extract from normal paragraphs
    for para in doc.paragraphs:
        line = para.text.strip()
        process_text_line(line, meta, headings, paragraphs)
    
    # Extract from tables (each cell)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for cell_paragraph in cell.paragraphs:
                    line = cell_paragraph.text.strip()
                    process_text_line(line, meta, headings, paragraphs)
    
    return meta, headings, paragraphs

# -----------------------------
# 4. Heading difference detection
# -----------------------------
def find_heading_differences(headings_v1, headings_v2):
    """
    Uses set differences to find added/removed headings.
    Each heading is stored as a string "H2: My heading text".
    Returns a dict with sets: {"added": set(...), "removed": set(...), "common": set(...)}
    NOTE: If you want to detect 'renamed' headings more robustly, 
    you'd need a more advanced approach (e.g., fuzzy matching).
    """
    # Convert list of (tag, text) -> single string "H2: My heading"
    set_v1 = set(f"{tag}: {text}" for tag, text in headings_v1)
    set_v2 = set(f"{tag}: {text}" for tag, text in headings_v2)
    
    added = set_v2 - set_v1
    removed = set_v1 - set_v2
    common = set_v1 & set_v2  # unchanged or identical strings
    
    return {"added": added, "removed": removed, "common": common}

# -----------------------------
# 5. AI Summarization: heading & paragraph differences
# -----------------------------
def generate_ai_summary(old_paragraphs, new_paragraphs, heading_diffs):
    """
    Calls OpenAI to produce a bullet-point list of heading diffs 
    and a short paragraph summarizing overall changes in paragraphs.
    """
    if not openai.api_key:
        return "OpenAI API key not provided; cannot generate AI summary."

    # Format heading diffs into bullet points for the prompt
    heading_diff_text = []
    if heading_diffs["added"]:
        heading_diff_text.append("**Added Headings**:")
        for h in heading_diffs["added"]:
            heading_diff_text.append(f"- {h}")
    if heading_diffs["removed"]:
        heading_diff_text.append("**Removed Headings**:")
        for h in heading_diffs["removed"]:
            heading_diff_text.append(f"- {h}")
    if heading_diffs["common"]:
        # Only mention this if you want to highlight headings that remained the same
        # heading_diff_text.append("**Unchanged Headings**:")
        # for h in heading_diffs["common"]:
        #     heading_diff_text.append(f"- {h}")
        pass

    bullet_list_for_prompt = "\n".join(heading_diff_text)
    
    prompt = (
        "You are a content analyst. Two versions of a document exist. "
        "Please do two things:\n\n"
        "1) Provide a bullet-point summary of heading differences "
        "(which headings were added, removed, or changed). See below:\n"
        f"{bullet_list_for_prompt}\n\n"
        "2) Provide a concise summary of the major paragraph-level changes between Version 1 and Version 2.\n\n"
        "VERSION 1 PARAGRAPHS:\n"
        f"{'\n'.join(old_paragraphs)}\n\n"
        "VERSION 2 PARAGRAPHS:\n"
        f"{'\n'.join(new_paragraphs)}\n\n"
        "Format your answer with bullet points for the headings, then a short paragraph describing the changes."
    )
    
    response = openai.ChatCompletion.create(
        model="gpt-4",  # or "gpt-3.5-turbo"
        messages=[
            {"role": "system", "content": "You are an expert content analyst."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3
    )
    return response["choices"][0]["message"]["content"].strip()

# -----------------------------
# 6. Streamlit UI
# -----------------------------
enable_ai_summarization = st.checkbox("Enable AI-powered summarization (headings + paragraphs)")

# Upload multiple docx files
uploaded_files = st.file_uploader(
    "Upload .docx files (Content Brief, V1, V2, etc.)", 
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
            meta_v1, headings_v1, paragraphs_v1 = file_versions[v1]["meta"], file_versions[v1]["headings"], file_versions[v1]["paragraphs"]
            meta_v2, headings_v2, paragraphs_v2 = file_versions[v2]["meta"], file_versions[v2]["headings"], file_versions[v2]["paragraphs"]
            
            # Display metadata changes
            st.subheader("🔍 Metadata Changes")
            for key in ["Meta Title", "H1", "URL"]:
                old_val = meta_v1.get(key, "")
                new_val = meta_v2.get(key, "")
                st.write(f"**{key}:** `{old_val}` → `{new_val}`")
            
            # Show side-by-side heading list (optional)
            st.subheader("📌 Heading Comparisons (Side-by-Side)")
            for (h1_tag, h1_txt), (h2_tag, h2_txt) in zip_longest(headings_v1, headings_v2, fillvalue=("", "")):
                if not (h1_tag or h1_txt or h2_tag or h2_txt):
                    continue
                st.write(f"- **{h1_tag or 'N/A'}**: `{h1_txt}` → **{h2_tag or 'N/A'}**: `{h2_txt}`")
            
            # Identify added/removed headings
            heading_diffs = find_heading_differences(headings_v1, headings_v2)
            
            st.subheader("✅ Added / ❌ Removed Headings")
            if heading_diffs["added"]:
                st.write("**Added:**")
                for h in heading_diffs["added"]:
                    st.write(f"- {h}")
            else:
                st.write("**No added headings**")
            
            if heading_diffs["removed"]:
                st.write("**Removed:**")
                for h in heading_diffs["removed"]:
                    st.write(f"- {h}")
            else:
                st.write("**No removed headings**")
            
            # AI Summaries
            if enable_ai_summarization:
                st.subheader("🤖 AI-Powered Summary (Headings + Paragraph Changes)")
                ai_summary = generate_ai_summary(paragraphs_v1, paragraphs_v2, heading_diffs)
                st.write(ai_summary)
            else:
                st.info("Enable AI summarization and provide an OpenAI API key to see a summary.")
