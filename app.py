import streamlit as st
import google.generativeai as genai
import tempfile
import os
import json
import time
from moviepy.editor import VideoFileClip, concatenate_videoclips

# --- SETUP ---
st.set_page_config(page_title="KamodAI Auto-Montage", layout="wide")

# --- HELPER FUNCTIONS ---
def time_to_seconds(time_str):
    """Converts MM:SS or MM:SS.ms to seconds (float)"""
    try:
        parts = list(map(float, time_str.split(':')))
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return parts[0] # Already in seconds
    except:
        return 0.0

# --- THE UI ---
st.title("🎬 KamodAI: Auto-Montage Maker")
st.markdown("### Upload up to 10 clips -> Get one 30-second viral video.")

with st.sidebar:
    st.header("⚙️ Director Settings")
    
    # API Key Handling (Secrets or Input)
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        api_key = st.text_input("Enter Gemini API Key", type="password")

    # Inputs
    uploaded_files = st.file_uploader("Upload Raw Footage (Max 10)", 
                                      type=['mp4', 'mov'], 
                                      accept_multiple_files=True)
    
    # Template Selector
    style_choice = st.radio("Choose Your Template:", [
        "⚡ Fast Paced (TikTok/Reels)",
        "🎥 Cinematic (Slow & Emotional)",
        "📹 Vlog (Casual Story)"
    ])
    
    # Target Duration
    total_duration = st.slider("Total Video Length (Seconds)", 15, 60, 30)
    
    generate_btn = st.button("✨ Create Magic Montage")

# --- THE BACKEND LOGIC ---
if generate_btn:
    if not api_key or not uploaded_files:
        st.error("❌ Please provide an API Key and at least one video file.")
        st.stop()

    # 1. Calculate Math
    num_clips = len(uploaded_files)
    clip_duration = total_duration / num_clips
    st.info(f"🧠 Logic: stitching {num_clips} clips. Each clip will be cut to ~{clip_duration:.2f} seconds.")

    # 2. Start Processing
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash') # Flash is fast & cheap
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    processed_subclips = []
    
    # Create a temporary directory to store files
    temp_dir = tempfile.mkdtemp()

    try:
        for i, uploaded_file in enumerate(uploaded_files):
            status_text.write(f"🎞️ Analyzing Clip {i+1}/{num_clips}: {uploaded_file.name}...")
            
            # Save file to disk
            temp_file_path = os.path.join(temp_dir, uploaded_file.name)
            with open(temp_file_path, "wb") as f:
                f.write(uploaded_file.read())
            
            # Upload to Gemini
            video_file = genai.upload_file(path=temp_file_path)
            
            # Wait for Gemini to process the video
            while video_file.state.name == "PROCESSING":
                time.sleep(1)
                video_file = genai.get_file(video_file.name)

            # --- THE PROMPT ---
            # We customize the prompt based on the style choice
            style_instruction = "Focus on high-energy motion."
            if "Cinematic" in style_choice:
                style_instruction = "Focus on stable, beautiful aesthetic shots."
            elif "Vlog" in style_choice:
                style_instruction = "Focus on faces and reactions."

            prompt = f"""
            I am building a video montage. 
            Act as a professional film editor.
            Watch this video and find the SINGLE BEST segment to use.
            
            Context: {style_instruction}
            Required Duration: EXACTLY {clip_duration} seconds.
            
            Output strictly JSON:
            {{
              "start": "MM:SS.ms",
              "end": "MM:SS.ms",
              "reason": "why this part was chosen"
            }}
            """

            # Ask Gemini
            response = model.generate_content([video_file, prompt])
            
            # Parse Answer
            try:
                # Clean JSON
                text = response.text.replace("```json", "").replace("```", "")
                data = json.loads(text)
                
                start_t = time_to_seconds(data["start"])
                end_t = time_to_seconds(data["end"])
                
                # Verify duration isn't wildly off (safety check)
                if (end_t - start_t) > (clip_duration + 2): 
                    end_t = start_t + clip_duration

                # Cut the video using MoviePy
                original_clip = VideoFileClip(temp_file_path)
                
                # Handle edge case if AI asks for time outside video length
                if end_t > original_clip.duration:
                    end_t = original_clip.duration
                    start_t = max(0, end_t - clip_duration)

                subclip = original_clip.subclip(start_t, end_t)
                
                # Resize to standard height (vertical 9:16 or horizontal) - Optional stability fix
                # subclip = subclip.resize(height=1080) 
                
                processed_subclips.append(subclip)
                st.write(f"✅ Clip {i+1}: Kept {data['start']} to {data['end']} ({data['reason']})")
                
            except Exception as e:
                st.warning(f"⚠️ Could not process clip {i+1} (AI Error): {e}")
                # Fallback: Just take the first few seconds if AI fails
                try:
                    fallback_clip = VideoFileClip(temp_file_path).subclip(0, clip_duration)
                    processed_subclips.append(fallback_clip)
                except:
                    pass

            progress_bar.progress((i + 1) / num_clips)

        # 3. Stitch Everything
        if processed_subclips:
            status_text.write("🧵 Stitching clips together...")
            final_video = concatenate_videoclips(processed_subclips, method="compose")
            
            output_path = os.path.join(temp_dir, "kamodai_final.mp4")
            final_video.write_videofile(output_path, codec="libx264", audio_codec="aac", fps=24)
            
            st.success("🎉 Montage Ready!")
            st.video(output_path)
            
            with open(output_path, "rb") as f:
                st.download_button("Download Video", f, "kamodai_montage.mp4", "video/mp4")
        else:
            st.error("Something went wrong. No clips were generated.")

    except Exception as e:
        st.error(f"System Error: {e}")
