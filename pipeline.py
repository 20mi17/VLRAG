import os
import json
import re
from pathlib import Path
from openai import OpenAI
from supabase import create_client, Client
from tqdm import tqdm  # Import progress bar
from config import get_settings

settings = get_settings()

client = OpenAI(api_key=settings.openai_api_key)

# Use service_role_key for backend scripts to bypass RLS
supa_key = settings.supabase_service_role_key if settings.supabase_service_role_key else settings.supabase_anon_key
supabase: Client = create_client(settings.supabase_url, supa_key)

def clean_json_response(content: str) -> str:
    """Helper to strip markdown code blocks from LLM response"""
    content = re.sub(r'^```(?:json)?', '', content.strip(), flags=re.MULTILINE)
    content = re.sub(r'```$', '', content.strip(), flags=re.MULTILINE)
    return content.strip()


def limit_to_first_n_pages(text: str, n: int = 3) -> str:
    """Return the text composed of the first `n` pages.

    Pages are detected in this order:
    - form-feed character ("\f")
    - simple "Page <number>" markers on their own line
    If no page delimiters are found the original text is returned.
    """
    if not text:
        return text

    # Prefer explicit form-feed page breaks
    if "\f" in text:
        pages = text.split("\f")
    else:
        # Fallback: split on common "Page <num>" markers
        pages = re.split(r"\n\s*Page\s+\d+\b", text)

    if len(pages) <= n:
        return text

    return "\n\n".join(pages[:n])

def detect_headings(text: str) -> list[dict]:
    """Use LLM to identify chapter headings and structure"""
    prompt = f"""Analyze this clinical document and identify all headings and their hierarchy.
    Return a strictly valid JSON array of objects with these exact keys: "heading_text", "level" (integer 1-3), and "start_position" (integer index).
    It's very possible you will encounter an initial list of all chapter headings - ignore that and look for the actual headings, likely with new lines before and after.

    Document:
    {text[:5000]}
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"} 
        )
        
        content = response.choices[0].message.content
        cleaned_content = clean_json_response(content)
        data = json.loads(cleaned_content)
        
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, list):
                    data = value
                    break
        
        if not isinstance(data, list):
            return []
            
        validated_data = []
        for item in data:
            if isinstance(item, dict) and 'start_position' in item:
                validated_data.append(item)
                
        return validated_data

    except Exception as e:
        print(f"Warning: Heading detection failed ({e}). Treating as single chunk.")
        return []

def chunk_by_headings(text: str, headings: list[dict]) -> list[dict]:
    """Split document into chunks based on detected headings"""
    if not headings:
        return [{
            'heading': 'General',
            'level': 1,
            'content': text,
            'position': 0
        }]

    chunks = []
    
    for i, heading in enumerate(headings):
        start = heading['start_position']
        if i < len(headings) - 1:
            end = headings[i+1]['start_position']
        else:
            end = len(text)
        
        chunk_content = text[start:end].strip()
        
        if not chunk_content:
            continue

        chunks.append({
            'heading': heading.get('heading_text', 'Untitled'),
            'level': heading.get('level', 1),
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
    if not section_summaries:
        return ""

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

def process_document(text: str, filename: str, source: str):
    """Main pipeline: Process text content → Supabase tables"""
    print(f"Processing {filename}...")
    
    # Insert document record
    doc_response = supabase.table('documents').insert({
        'title': filename,
        'source': source
    }).execute()
    
    if hasattr(doc_response, 'data') and doc_response.data:
        doc_id = doc_response.data[0]['id']
    else:
        print(f"Error creating document record for {filename}")
        return

    # Detect structure
    headings = detect_headings(text)
    print(f"  - Detected {len(headings)} headings")
    
    # Chunk by headings
    chunks = chunk_by_headings(text, headings)
    print(f"  - Created {len(chunks)} chunks")
    
    # Group chunks by chapter
    chapters = {}
    current_chapter = "General"
    
    for chunk in chunks:
        if chunk['level'] == 1:
            current_chapter = chunk['heading']
            chapters[current_chapter] = []
        elif current_chapter not in chapters:
             chapters[current_chapter] = []
        
        chapters[current_chapter].append(chunk)
    
    # Calculate total operations for progress bar
    total_chunks = len(chunks)
    
    print("  - Generating summaries...")
    
    # Use tqdm for a progress bar
    with tqdm(total=total_chunks, unit="chunk") as pbar:
        for chapter_name, chapter_chunks in chapters.items():
            if not chapter_chunks:
                continue
                
            section_summaries = []
            
            for chunk in chapter_chunks:
                try:
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
                    
                    pbar.update(1)  # Update progress bar
                    
                except Exception as e:
                    print(f"\nError processing chunk: {e}")
            
            # Create chapter summary (outside the chunk loop)
            if section_summaries:
                chapter_summary = create_chapter_summary(section_summaries, chapter_name)
                
                # Update all chunks in this chapter
                for chunk in chapter_chunks:
                    supabase.table('chunks').update({
                        'chapter_summary': chapter_summary
                    }).match({
                        'document_id': doc_id,
                        'section_heading': chunk['heading']
                    }).execute()
    
    print(f"\n✓ Processed {filename}")

def process_storage_bucket():
    """Process all .txt files from Supabase Storage bucket"""
    bucket_name = "Medical Guidelines"
    folder_path = "Diabetes Text/text"
    
    print(f"Connecting to Storage Bucket: {bucket_name}...")
    
    try:
        files = supabase.storage.from_(bucket_name).list(folder_path)
        
        if not files:
            print("No files found.")
            return

        for file in files:
            if file['name'].endswith('.txt'):
                file_path_in_bucket = f"{folder_path}/{file['name']}"
                print(f"\nDownloading {file_path_in_bucket}...")
                
                content_bytes = supabase.storage.from_(bucket_name).download(file_path_in_bucket)
                text_content = content_bytes.decode('utf-8')
                # Limit to the first 3 pages to avoid processing whole documents
                text_content = limit_to_first_n_pages(text_content, 3)
                
                process_document(
                    text=text_content, 
                    filename=file['name'], 
                    source=f"supabase://{bucket_name}/{file_path_in_bucket}"
                )
            else:
                pass 
                
    except Exception as e:
        print(f"✗ Error: {e}")

if __name__ == "__main__":
    process_storage_bucket()