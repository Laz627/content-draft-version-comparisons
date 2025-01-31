import streamlit as st
import docx
import re
import openai
from itertools import zip_longest

st.title("📝 SEO Content Draft Comparator")
st.write("Upload different versions of your content to analyze heading, metadata, and paragraph changes.")

# 1. User-provided OpenAI API Key
openai_api_key = st.text_input("Enter your OpenAI API Key (optional):", type="password")
if openai_api_key:
    openai.api_key = openai_api_key

# 2. Function to extract headings, metadata, and paragraphs from .docx files
def extract_content(file):
    doc = docx.Document(file)
    headings = []
    meta = {"Meta Title": "", "H1": "", "URL": ""}
    paragraphs = []
    
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        
        # Extract Meta Title, H1, and URL (basic approach)
        if text.lower().startswith("meta title"):
            meta["Meta Title"] = text.split("meta title", 1)[-1].strip(": ").strip()
        elif text.lower().startswith("h1"):
            meta["H1"] = text.split("h1", 1)[-1].strip(": ").strip()
        elif text.lower().startswith("url"):
            meta["URL"] = text.split("url", 1)[-1].strip(": ").strip()
        
        # Extract headings in the form "H2: Some Heading"
        match = re.match(r'^(H[1-6]):\s*(.*)', text)
        if match:
            headings.append((match.group(1), match.group(2)))
        else:
            paragraphs.append(text)
    
    return meta, headings, paragraphs

# 3. Optional: AI-powered summarization of paragraph changes
def generate_ai_summary(old_text, new_text):
    if not openai.api_key:
        return "OpenAI API key not provided; cannot generate AI summary."
    
    prompt = (
        "Compare the following two versions of text and summarize the key differences:\n\n"
        f"Version 1:\n{old_text}\n\n"
        f"Version 2:\n{new_text}\n\n"
        "Provide a concise summary of changes."
    )
    
    # You can change 'gpt-4' to 'gpt-3.5-turbo' or another model if desired.
    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an expert content analyst."},
            {"role": "user", "content": prompt},
        ]
    )
    return response["choices"][0]["message"]["content"].strip()

# 4. Toggle for AI-powered summarization
enable_ai_paragraph = st.checkbox("Enable AI-powered summarization of paragraph changes")

# 5. Let users upload multiple .docx files
uploaded_files = st.file_uploader("Upload .docx files (Content Brief, V1, V2, etc.)", 
                                  accept_multiple_files=True, 
                                  type=["docx"])

if uploaded_files and len(uploaded_files) >= 2:
    # Process each file
    file_versions = {}
    for file in uploaded_files:
        meta, headings, paragraphs = extract_content(file)
        file_versions[file.name] = {
            "meta": meta,
            "headings": headings,
            "paragraphs": paragraphs
        }
    
    # Pick which versions to compare
    versions = list(file_versions.keys())
    v1 = st.selectbox("Select the first version to compare:", versions)
    v2 = st.selectbox("Select the second version to compare:", versions, 
                      index=1 if len(versions) > 1 else 0)
    
    if st.button("Compare Versions"):
        if v1 == v2:
            st.warning("You selected the same file for both versions. Please select different versions to compare.")
        else:
            meta_v1, headings_v1, paragraphs_v1 = file_versions[v1]["meta"], file_versions[v1]["headings"], file_versions[v1]["paragraphs"]
            meta_v2, headings_v2, paragraphs_v2 = file_versions[v2]["meta"], file_versions[v2]["headings"], file_versions[v2]["paragraphs"]
            
            st.subheader("🔍 Metadata Changes")
            for key in ["Meta Title", "H1", "URL"]:
                old_val = meta_v1.get(key, "")
                new_val = meta_v2.get(key, "")
                st.write(f"**{key}:** `{old_val}` → `{new_val}`")
            
            st.subheader("📌 Heading Changes")
            # Use zip_longest to handle different numbers of headings
            for (h1, t1), (h2, t2) in zip_longest(headings_v1, headings_v2, fillvalue=("", "")):
                # If there's no heading label or text, skip if both are empty
                if not (h1 or t1 or h2 or t2):
                    continue
                # If headings differ, show changes
                st.write(f"- **{h1 or h2}:** `{t1}` → `{t2}`")
            
            if enable_ai_paragraph:
                st.subheader("🤖 AI-Powered Summary of Paragraph Changes")
                old_text = "\n".join(paragraphs_v1)
                new_text = "\n".join(paragraphs_v2)
                ai_summary = generate_ai_summary(old_text, new_text)
                st.write(ai_summary)
