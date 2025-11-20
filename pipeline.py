import os
from pathlib import Path
from openai import OpenAI
from supabase import create_client
from config import get_settings

settings = get_settings()

client = OpenAI(api_key=settings.openai_api_key)
supabase = create_client(settings.supabase_url, settings.supabase_anon_key)

def detect_headings(text: str) -> list[dict]:
    """Use LLM to identify chapter headings and structure"""
    prompt = f"""Analyze this clinical document and identify all headings and their hierarchy.
    Return a JSON array of objects with: heading_text, level (1-3), and start_position.
    
    Document:
    {text[:5000]}  # First 5000 chars for efficiency
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    
    return eval(response.choices[0].message.content)

def chunk_by_headings(text: str, headings: list[dict]) -> list[dict]:
    """Split document into chunks based on detected headings"""
    chunks = []
    
    for i, heading in enumerate(headings):
        start = heading['start_position']
        end = headings[i+1]['start_position'] if i < len(headings)-1 else len(text)
        
        chunk_content = text[start:end].strip()
        
        chunks.append({
            'heading': heading['heading_text'],
            'level': heading['level'],
            'content': chunk_content,
            'position': i
        })
    
    return chunks

def summarize_chunk(content: str, heading: str) -> str:
    """Generate summary for a section using LLM"""
    prompt = f"""Summarize this clinical guideline section concisely (2-3 sentences).
    Focus on key clinical information, treatments, or recommendations.
    
    Section: {heading}
    Content: {content[:2000]}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    
    return response.choices[0].message.content

def create_chapter_summary(section_summaries: list[str], chapter_name: str) -> str:
    """Create chapter-wide summary from section summaries"""
    combined = "\n".join(section_summaries)
    
    prompt = f"""Create a comprehensive chapter summary from these section summaries.
    
    Chapter: {chapter_name}
    Section summaries:
    {combined}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    
    return response.choices[0].message.content

def process_document(file_path: str):
    """Main pipeline: txt file → Supabase tables"""
    # Read document
    with open(file_path, 'r', encoding='utf-8') as f:
        text = f.read()
    
    filename = Path(file_path).name
    
    # Insert document record
    doc_response = supabase.table('documents').insert({
        'title': filename,
        'source': file_path
    }).execute()
    
    doc_id = doc_response.data[0]['id']
    
    # Detect structure
    headings = detect_headings(text)
    
    # Chunk by headings
    chunks = chunk_by_headings(text, headings)
    
    # Group chunks by chapter (level 1 headings)
    chapters = {}
    current_chapter = None
    
    for chunk in chunks:
        if chunk['level'] == 1:
            current_chapter = chunk['heading']
            chapters[current_chapter] = []
        
        if current_chapter:
            chapters[current_chapter].append(chunk)
    
    # Process each chapter
    for chapter_name, chapter_chunks in chapters.items():
        section_summaries = []
        
        for chunk in chapter_chunks:
            # Summarize section
            summary = summarize_chunk(chunk['content'], chunk['heading'])
            section_summaries.append(summary)
            
            # Store in database
            supabase.table('chunks').insert({
                'document_id': doc_id,
                'section_heading': chunk['heading'],
                'content': chunk['content'],
                'summary': summary,
                'position_in_doc': chunk['position']
            }).execute()
        
        # Create chapter summary
        chapter_summary = create_chapter_summary(section_summaries, chapter_name)
        
        # Update all chunks in this chapter with chapter_summary
        for chunk in chapter_chunks:
            supabase.table('chunks').update({
                'chapter_summary': chapter_summary
            }).match({
                'document_id': doc_id,
                'section_heading': chunk['heading']
            }).execute()
    
    print(f"✓ Processed {filename}: {len(chunks)} chunks loaded")

def process_directory(directory_path: str):
    """Process all .txt files in a directory"""
    txt_files = Path(directory_path).glob('*.txt')
    
    for txt_file in txt_files:
        try:
            process_document(str(txt_file))
        except Exception as e:
            print(f"✗ Error processing {txt_file.name}: {e}")

if __name__ == "__main__":
    # Run pipeline
    process_directory('./documents')
