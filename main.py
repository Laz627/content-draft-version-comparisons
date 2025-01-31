import streamlit as st
import docx
import re
import spacy
import openai
import subprocess
from itertools import zip_longest

# Ensure spaCy model is available before loading
MODEL_NAME = "en_core_web_sm"
try:
    nlp = spacy.load(MODEL_NAME)
except OSError:
    st.info("Downloading spaCy language model. This may take a moment...")
    try:
        subprocess.run(["python", "-m", "spacy", "download", MODEL_NAME], check=True)
        nlp = spacy.load(MODEL_NAME)
    except Exception as e:
        st.error(f"Could not automatically install spaCy model. Please add '{MODEL_NAME}' to your environment or requirements.\nError: {e}")
        st.stop()

# Streamlit UI
st.title("📝 SEO Content Draft Comparator")
st.write("Upload different versions of your content to analyze heading, metadata, and paragraph changes.")

# User API Key Input
openai_api_key = st.text_input("Enter your OpenAI API Key:", type="password")
if openai_api_key:
    openai.api_key = openai_api_key

# Function to extract headings, metadata, and paragraphs from .docx files
def extract_content(file):
    doc = docx.Document(file)
    headings = []
    meta = {"Meta Title": "", "H1": "", "URL": ""}
    paragraphs = []
    
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        
        # Extract Meta Title, H1, and URL
        if text.lower().startswith("meta title"):
            meta["Meta Title"] = text.split("Meta Title")[-1].strip()
        elif text.lower().startswith("h1"):
            meta["H1"] = text.split("h1")[-1].strip()
        elif text.lower().startswith("url"):
            meta["URL"] = text.split("url")[-1].strip()
        
        # Extract headings (H1 - H6) in the form "H2: Some Heading"
        match = re.match(r'^(H[1-6]):\s*(.*)', text)
        if match:
            headings.append((match.group(1), match.group(2)))
        else:
            paragraphs.append(text)
    
    return meta, headings, paragraphs

# Function to generate AI-powered summary using OpenAI
def generate_ai_summary(old_text, new_text):
    prompt = (
        "Compare the following two versions of text and summarize the key differences:\n\n"
        f"Version 1:\n{old_text}\n\n"
        f"Version 2:\n{new_text}\n\n"
        "Provide a concise summary of changes."
    )
    
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an expert content analyst."},
            {"role": "user", "content": prompt}
        ]
    )
    
    return response["choices"][0]["message"]["content"].strip()

# Toggle for AI-powered paragraph tracking
enable_ai_paragraph = st.checkbox("Enable AI-powered sentence-level tracking for paragraph changes")

# Upload multiple .docx files
uploaded_files = st.file_uploader("Upload .docx files (Content Brief, V1, V2, etc.)", 
                                  accept_multiple_files=True, 
                                  type=["docx"])

if uploaded_files and len(uploaded_files) >= 2:
    file_versions = {}
    
    for file in uploaded_files:
        meta, headings, paragraphs = extract_content(file)
        file_versions[file.name] = {
            "meta": meta,
            "headings": headings,
            "paragraphs": paragraphs
        }
    
    # Let users pick which versions to compare
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
            for (h1, t1), (h2, t2) in zip_longest(headings_v1, headings_v2, fillvalue=("", "")):
                # If there's no heading label at all, skip
                if not h1 and not h2 and not t1 and not t2:
                    continue
                st.write(f"- **{h1 or h2}:** `{t1}` → `{t2}`")
            
            if enable_ai_paragraph and openai_api_key:
                st.subheader("🤖 AI-Powered Summary of Paragraph Changes")
                ai_summary = generate_ai_summary("\n".join(paragraphs_v1), "\n".join(paragraphs_v2))
                st.write(ai_summary)
            elif enable_ai_paragraph and not openai_api_key:
                st.warning("Please enter your OpenAI API key to use AI-powered summarization.")
