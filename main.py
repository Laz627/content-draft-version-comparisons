import streamlit as st
import difflib
import docx
import re
import spacy
import openai
from collections import defaultdict
from itertools import zip_longest
from bs4 import BeautifulSoup

# Streamlit UI
st.title("📝 SEO Content Draft Comparator")
st.write("Upload different versions of your content to analyze heading, metadata, and paragraph changes.")

# User API Key Input
openai_api_key = st.text_input("Enter your OpenAI API Key:", type="password")
if openai_api_key:
    openai.api_key = openai_api_key

# Load NLP model for summarization (Ensure it's downloaded)
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    st.warning("Downloading spaCy language model. This may take a moment...")
    import subprocess
    subprocess.run(["python", "-m", "spacy", "download", "en_core_web_sm"])
    nlp = spacy.load("en_core_web_sm")

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
            meta["H1"] = text.split("H1")[-1].strip()
        elif text.lower().startswith("url"):
            meta["URL"] = text.split("URL")[-1].strip()
        
        # Extract headings (H1 - H6)
        match = re.match(r'^(H[1-6]):\s*(.*)', text)
        if match:
            headings.append((match.group(1), match.group(2)))
        else:
            paragraphs.append(text)
    
    return meta, headings, paragraphs

# Function to generate AI-powered summary using OpenAI
def generate_ai_summary(old_text, new_text):
    prompt = f"Compare the following two versions of text and summarize the key differences:\n\nVersion 1:\n{old_text}\n\nVersion 2:\n{new_text}\n\nProvide a concise summary of changes."
    
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "system", "content": "You are an expert content analyst."},
                  {"role": "user", "content": prompt}]
    )
    
    return response["choices"][0]["message"]["content"].strip()

# Toggle for AI-powered paragraph tracking
enable_ai_paragraph = st.checkbox("Enable AI-powered sentence-level tracking for paragraph changes")

# Upload multiple .docx files
uploaded_files = st.file_uploader("Upload .docx files (Content Brief, V1, V2, etc.)", accept_multiple_files=True, type=["docx"])

if uploaded_files and len(uploaded_files) >= 2:
    file_versions = {}
    
    for file in uploaded_files:
        meta, headings, paragraphs = extract_content(file)
        file_versions[file.name] = {"meta": meta, "headings": headings, "paragraphs": paragraphs}
    
    # Select versions for comparison
    versions = list(file_versions.keys())
    v1 = st.selectbox("Select the first version to compare:", versions)
    v2 = st.selectbox("Select the second version to compare:", versions, index=1 if len(versions) > 1 else 0)
    
    if st.button("Compare Versions"):
        meta_v1, headings_v1, paragraphs_v1 = file_versions[v1]["meta"], file_versions[v1]["headings"], file_versions[v1]["paragraphs"]
        meta_v2, headings_v2, paragraphs_v2 = file_versions[v2]["meta"], file_versions[v2]["headings"], file_versions[v2]["paragraphs"]
        
        st.subheader("🔍 Metadata Changes")
        for key in ["Meta Title", "H1", "URL"]:
            st.write(f"**{key}:** {meta_v1[key]} → {meta_v2[key]}")
        
        st.subheader("📌 Heading Changes")
        for (h1, t1), (h2, t2) in zip_longest(headings_v1, headings_v2, fillvalue=("", "")):
            st.write(f"**{h1 or h2}:** {t1} → {t2}")
        
        if enable_ai_paragraph and openai_api_key:
            st.subheader("🤖 AI-Powered Summary of Paragraph Changes")
            ai_summary = generate_ai_summary("\n".join(paragraphs_v1), "\n".join(paragraphs_v2))
            st.write(ai_summary)
