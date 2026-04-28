
import os
from google.cloud import texttospeech_v1beta1 as texttospeech

def list_all_voices():
    creds_file = r"C:\Users\gfran\audiobook-maker-data\audiobook-maker-488211-e80867ce5414.json"
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds_file
    client = texttospeech.TextToSpeechClient()
    response = client.list_voices()
    
    print(f"Total voices: {len(response.voices)}")
    chirp_voices = [v.name for v in response.voices if "Chirp" in v.name]
    print(f"Voices with 'Chirp' in name: {len(chirp_voices)}")
    for name in chirp_voices[:20]:
        print(f" - {name}")
        
    if not chirp_voices:
        print("No Chirp voices found. Listing first 20 voices:")
        for v in response.voices[:20]:
            print(f" - {v.name} ({v.language_codes})")

if __name__ == "__main__":
    list_all_voices()
