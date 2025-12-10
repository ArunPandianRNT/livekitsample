"""
RESH & THOSH - LiveKit Avatar Agent
Gemini 2.5 Flash + Sarvam AI + Simli + JSON-based RAG
Enhanced with Voice Support + Excel Logging + Manual vs Automation
"""

import logging
import os
import re
import json
import asyncio
from pathlib import Path
from typing import List, Dict, Optional
from dotenv import load_dotenv
import datetime
from livekit.agents import Agent, AgentSession, JobContext, cli, WorkerOptions
from livekit import rtc
from livekit.plugins import google, simli, sarvam, anam, groq 
from livekit.plugins.bey.avatar import AvatarSession as BeyAvatarSession # type: ignore

# Excel Logging Imports
import openpyxl 
from openpyxl import Workbook

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("resh-thosh-agent")

# ============================================================
# EXCEL LOGGING SETUP
# ============================================================
EXCEL_FILE = "messages.xlsx"
EXCEL_LOCK = asyncio.Lock()
excel_workbook: Optional[Workbook] = None 
excel_sheet: Optional[openpyxl.worksheet.worksheet.Worksheet] = None


async def initialize_excel():
    """Load or create the Excel workbook and set up headers, handling corrupt files."""
    global excel_workbook, excel_sheet
    async with EXCEL_LOCK:
        try:
            # 1. Check if file exists
            if os.path.exists(EXCEL_FILE):
                try:
                    # 2. Attempt to load the existing workbook
                    excel_workbook = openpyxl.load_workbook(EXCEL_FILE)
                    excel_sheet = excel_workbook.active
                    logger.info(f"💾 Loaded existing Excel workbook: {EXCEL_FILE}")
                    return # Successfully loaded, exit function
                
                except Exception as load_error:
                    # 3. Handle the 'File is not a zip file' error (or any other load error)
                    if "zip file" in str(load_error):
                        logger.warning(f"⚠️ Existing Excel file corrupted: {load_error}. Attempting to create new file.")
                    else:
                        logger.error(f"❌ Unknown load error: {load_error}")
                        raise load_error # Re-raise if it's a non-expected error
                    
                    # Delete the corrupted file
                    os.remove(EXCEL_FILE)
                    logger.info(f"🗑️ Deleted corrupted file: {EXCEL_FILE}")
            
            # 4. If the file didn't exist, or was deleted due to corruption, create a new one
            excel_workbook = Workbook()
            excel_sheet = excel_workbook.active
            excel_sheet.title = "Agent Log"
            # Write headers
            excel_sheet.append(["Timestamp", "User Request", "Agent Response"])
            excel_workbook.save(EXCEL_FILE)
            logger.info(f"💾 Created new Excel workbook: {EXCEL_FILE}")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Excel: {e}")
            excel_workbook = None
            excel_sheet = None


async def log_interaction(user_request: str, agent_response: str):
    """Write the user request and agent response to the Excel sheet."""
    global excel_workbook, excel_sheet
    
    if not excel_sheet or not excel_workbook:
        logger.warning("⚠️ Excel logging not active (workbook not initialized).")
        return
        
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    async with EXCEL_LOCK:
        try:
            excel_sheet.append([timestamp, user_request, agent_response])
            excel_workbook.save(EXCEL_FILE)
            logger.info(f"📝 Logged interaction to Excel at {timestamp}")
            logger.info(f"   User: '{user_request[:50]}...'")
            logger.info(f"   Agent: '{agent_response[:50]}...'")
        except Exception as e:
            logger.error(f"❌ Failed to log to Excel: {e}")


# ============================================================
# JSON CONTENT LOADER & SIMPLE RAG
# ============================================================
class JSONContentLoader:
    def __init__(self, content_directory: str = "rag_content"):
        self.content_directory = Path(content_directory)
        self.pages_content = {}
        
    def load_json_files(self):
        """Load all JSON files from the content directory"""
        if not self.content_directory.exists():
            logger.error(f"❌ Content directory not found: {self.content_directory}")
            self._use_fallback_content()
            return
        
        json_files = list(self.content_directory.glob("*.json"))
        
        if not json_files:
            logger.warning(f"⚠️ No JSON files found in {self.content_directory}")
            self._use_fallback_content()
            return
        
        logger.info(f"📂 Loading content from {len(json_files)} JSON files...")
        
        for json_file in json_files:
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    
                if not content:
                    logger.warning(f"  ⚠️ Skipped empty file: {json_file}")
                    continue
                    
                data = json.loads(content)
                
                key = json_file.stem
                self.pages_content[key] = data
                
                sections_count = len(data.get('sections', []))
                logger.info(f"  ✅ Loaded: {key}.json - {data.get('title', 'Untitled')} ({sections_count} sections)")
                
            except json.JSONDecodeError as e:
                logger.error(f"  ❌ Invalid JSON in {json_file}: {e}")
            except Exception as e:
                logger.error(f"  ❌ Error loading {json_file}: {e}")
        
        logger.info(f"📊 Content loading complete: {len(self.pages_content)} pages loaded")
    
    def _use_fallback_content(self):
        """Fallback content structure with Manual vs Automation"""
        self.pages_content = {
            'home': {
                'title': 'Home',
                'sections': [
                    {
                        'heading': 'Intro',
                        'content': 'Future-ready solutions built to streamline operations, elevate traveler experiences, and drive growth in the dynamic travel industry.'
                    }
                ]
            },
            'about': {
                'title': 'About',
                'sections': [
                    {
                        'heading': 'Overview',
                        'content': 'At Resh and Thosh, we are committed to leveraging the latest technological advancements to transform the way your customers experience travel, ensuring efficiency and satisfaction. The founder of Resh and Thosh is **Manoj Krishnan**.'
                    },
                    {
                        'heading': 'Mission',
                        'content': 'Empowering businesses through conversational AI, automation and video avatars.'
                    }
                ]
            },
            'products': {
                'title': 'Products',
                'sections': [
                    {
                        'heading': 'Animate AI',
                        'content': 'AI-Powered Email Booking Solution for flight bookings. Automates email processing and booking for corporate travel companies.',
                        'url': 'https://reshandthosh.com/products-2/'
                    },
                    {
                        'heading': 'OLMS',
                        'content': 'Online Login Management System for secure airline booking operations with user management and access control.',
                        'url': 'https://reshandthosh.com/products-2/'
                    },
                    {
                        'heading': 'IBE',
                        'content': 'Internet Booking Engine providing seamless online booking experiences with real-time availability and secure payment processing.',
                        'url': 'https://reshandthosh.com/products-2/'
                    },
                    {
                        'heading': 'Manual vs Automation',
                        'content': 'Manual processes cost more due to high labor hours, slower output, and frequent errors, which increases overall operational expense. Automation reduces time, labor cost, and mistakes, allowing the same work to be completed faster and more accurately. ROI is calculated as: ROI = (Manual Cost – Automation Cost) / Automation Cost × 100 to measure how much value automation generates. If automation cost is ₹1,00,000 and it saves ₹60,000/month in manual work, the payback period is less than 2 months and ROI exceeds 300–500%. Overall, automation provides higher efficiency, lower cost, and faster scalability, delivering significant long-term financial and productivity benefits',
                        'url': 'https://reshandthosh.com/products-2/'
                    }
                ]
            },
            'contact': {
                'title': 'Contact',
                'sections': [
                    {
                        'heading': 'Get in Touch',
                        'content': 'Contact us to learn more about our products and services.',
                        'url': 'https://reshandthosh.com/contact-us/'
                    }
                ]
            }
        }
        logger.info("✅ Loaded fallback content structure with Manual vs Automation")


class SimpleRAG:
    def __init__(self):
        self.chunks = []
        self.product_sections = {}
        self.metadata = []
        self.full_content = {}
        self.page_urls = {}

    def add(self, text: str, metadata: dict = None):
        """Add text chunks with optional metadata"""
        chunk_size = 800
        overlap = 150
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            self.chunks.append(chunk)
            self.metadata.append(metadata or {})
            start = end - overlap
    
    def add_product_section(self, product_name: str, content: str, url: str = None):
        """Add a dedicated product section for targeted retrieval"""
        self.product_sections[product_name.lower()] = {
            'content': content,
            'url': url
        }
        logger.info(f"  💾 Stored product section: {product_name} ({len(content)} chars)")
    
    def add_full_page(self, page_name: str, content: str, url: str = None):
        """Store complete page content and URL for specific queries"""
        self.full_content[page_name.lower()] = content
        if url:
            self.page_urls[page_name.lower()] = url

    def search(self, query: str, top_k: int = 4, is_greeting: bool = False) -> str:
        """Search RAG with optional greeting flag to avoid false matches"""
        query_lower = query.lower()
        
        if is_greeting:
            logger.info("🎯 Greeting query - returning intro content")
            if 'home' in self.full_content:
                return self.full_content['home']
            return ""
        
        product_keywords = {
            'animate': ['animate', 'animate ai', 'anima', 'email booking', 'flight booking'],
            'olms': ['olms', 'olm', 'online login', 'login management', 'user management', 'agent management', 'online login management system'],
            'ibe': ['ibe', 'internet booking', 'booking engine', 'online booking'],
            'manual vs automation': ['manual vs automation', 'manual versus automation', 'automation roi', 'automation cost', 'manual cost', 'automation benefit', 'payback period', 'roi calculation', "roi"]
        }
        
        for product, keywords in product_keywords.items():
            for keyword in keywords:
                if keyword in query_lower:
                    if product in self.product_sections:
                        section = self.product_sections[product]
                        logger.info(f"🎯 Direct product match: {product} (matched keyword: '{keyword}')")
                        return section['content']
        
        founder_words = ['founder', 'ceo', 'started', 'owner', 'founders', 'established']
        if any(word in query_lower for word in founder_words):
            about_content = self._get_page_content('about')
            if about_content:
                logger.info(f"🎯 Founder/About query detected")
                return about_content
        
        page_checks = {
            'products': ['product', 'products', 'offer', 'offerings', 'solutions'],
            'about': ['company', 'who are you', 'mission', 'vision'],
            'contact': ['contact', 'reach', 'get in touch', 'email', 'phone', 'address']
        }
        
        for page, keywords in page_checks.items():
            if any(re.search(r'\b' + word + r'\b', query_lower) for word in keywords):
                page_content = self._get_page_content(page)
                if page_content:
                    logger.info(f"🎯 General {page} query")
                    return page_content
        
        words = set(re.findall(r"[a-zA-Z]{3,}", query_lower))
        
        if not words:
            return ""
        
        scores = []
        for idx, chunk in enumerate(self.chunks):
            chunk_lower = chunk.lower()
            chunk_words = set(re.findall(r"[a-zA-Z]{3,}", chunk_lower))
            
            score = len(words & chunk_words) * 2
            
            for product in product_keywords.keys():
                if product in query_lower and product in chunk_lower:
                    score += 30
            
            meta = self.metadata[idx]
            if meta.get('page') == 'products' and any(word in query_lower for word in page_checks['products']):
                score += 10
            
            scores.append((score, chunk, idx))
        
        scores.sort(reverse=True, key=lambda x: x[0])
        
        relevant_chunks = [(score, chunk) for score, chunk, _ in scores[:top_k] if score > 0]
        
        if relevant_chunks:
            result = "\n\n---\n\n".join(chunk for _, chunk in relevant_chunks)
            logger.info(f"RAG Search: '{query[:50]}' → Found {len(relevant_chunks)} chunks (scores: {[s for s, _ in relevant_chunks]})")
            return result
        
        logger.warning(f"RAG Search: '{query[:50]}' → No relevant chunks found")
        return ""
    
    def _get_page_content(self, page_name: str) -> str:
        """Get content for a specific page"""
        return self.full_content.get(page_name.lower(), "")


content_loader = JSONContentLoader()
rag = SimpleRAG()


def build_rag_from_json():
    """Build RAG index from loaded JSON content"""
    if not content_loader.pages_content:
        logger.error("❌ No content loaded!")
        return
    
    logger.info("🏗️ Building RAG index from JSON content...")
    
    for page_key, page_data in content_loader.pages_content.items():
        title = page_data.get('title', page_key)
        sections = page_data.get('sections', [])
        
        logger.info(f"  🔍 Processing page: {page_key}, sections count: {len(sections)}")
        
        full_page_text = f"Page: {title}\n\n"
        page_url = None
        
        for idx, section in enumerate(sections):
            heading = section.get('heading', '')
            content = section.get('content', '')
            url = section.get('url', '')
            
            section_text = f"{heading}\n{content}"
            
            full_page_text += section_text + "\n\n"
            
            if content:
                rag.add(
                    section_text,
                    metadata={
                        'page': page_key,
                        'title': title,
                        'heading': heading,
                        'has_url': bool(url)
                    }
                )
            
            if page_key.lower() == 'products' and heading and content:
                heading_lower = heading.lower()
                product_name = None
                
                if 'animate' in heading_lower:
                    product_name = 'animate'
                elif 'olms' in heading_lower:
                    product_name = 'olms'
                elif 'ibe' in heading_lower:
                    product_name = 'ibe'
                elif 'manual vs automation' in heading_lower or 'manual versus automation' in heading_lower:
                    product_name = 'manual vs automation'
                
                if product_name:
                    rag.add_product_section(product_name, section_text.strip(), url)
            
            if url and not page_url:
                page_url = url
        
        rag.add_full_page(page_key, full_page_text.strip(), page_url)
        logger.info(f"  ✅ Indexed: {page_key} ({len(sections)} sections, URL present: {bool(page_url)})")
    
    logger.info(f"📚 RAG Built: {len(rag.chunks)} chunks, {len(rag.product_sections)} product sections, {len(rag.full_content)} pages")


def should_wave(user_message: str) -> bool:
    """Detect if user greeting warrants a wave response"""
    greetings = ['hi', 'hello', 'hey', 'good morning', 'good afternoon', 'good evening', 'greetings', 'namaste']
    message_lower = user_message.lower().strip()
    
    if any(greeting == message_lower for greeting in greetings):
        return True
    
    if message_lower.startswith(tuple(greetings)) and len(message_lower.split()) <= 3:
        return True
    
    return False


# ============================================================
# MAIN ENTRYPOINT - Audio Only Version
# ============================================================
async def entrypoint(ctx: JobContext):
    logger.info("🚀 JOB DISPATCHED - Starting Resh & Thosh Avatar Agent (Audio Only)")

    # Dictionary to track pending conversations
    pending_log = {"user_request": None, "agent_response": None}

    try:
        # Initialize Excel logging
        await initialize_excel()

        # Load JSON content & build RAG
        content_loader.load_json_files()
        build_rag_from_json()
        
        if not rag.chunks:
            logger.error("❌ No content to build RAG from! Exiting...")
            await ctx.connect()
            await AgentSession(llm=google.LLM(model="gemini-2.5-flash-lite")).start(
                agent=Agent(instructions="Say: I apologize, my knowledge base is currently unavailable. I am the Resh & Thosh agent. Please try again later."), 
                room=ctx.room
            )
            return

        # Connect to room
        await ctx.connect()
        logger.info("🔗 Connected to LiveKit Room")

        # Create Agent Session
        session = AgentSession(
            stt=sarvam.STT(
                language="en-IN",
                model="saarika:v2.5",
                api_key=os.getenv("SARVAM_API_KEY"),
            ),
            llm=groq.LLM(
                model="llama-3.1-8b-instant",
                temperature=0.7,
            ),
            tts=sarvam.TTS(
                target_language_code="en-IN",
                model="bulbul:v2",
                speaker="anushka",
                api_key=os.getenv("SARVAM_API_KEY"),
            ),
        )
        logger.info("🧠 Agent Session Created")

        # Beyound Presence Avatar
        avatar = BeyAvatarSession(
            api_key=os.getenv("BEY_API_KEY"),
            avatar_id=os.getenv("BEY_AVATAR_ID"),
        )
        await avatar.start(session, room=ctx.room)
        logger.info("👤 Beyond Presence Avatar Started")

        #  Anam Avatar
        # avatar = anam.AvatarSession(
        #     # Pass Anam API Key directly (or set as ANAM_API_KEY environment variable)
        #     api_key=os.getenv("ANAM_API_KEY"),
        #     # Configure the specific avatar persona
        #     persona_config=anam.PersonaConfig(
        #         name="ReshAndThosh Agent", 
        #         avatarId=os.getenv("ANAM_AVATAR_ID"), 
        #     )
        # )
        # await avatar.start(session, room=ctx.room)
        # logger.info("👤 Anam Avatar Started")


        # Start Simli Avatar
        # avatar = simli.AvatarSession(
        #     simli_config=simli.SimliConfig(
        #         api_key=os.getenv("SIMLI_API_KEY"),
        #         face_id=os.getenv("SIMLI_FACE_ID"),
        #     )
        # )
        # await avatar.start(session, room=ctx.room)
        # logger.info("👤 Simli Avatar Started")

        # Create agent
        agent = Agent(
            instructions="""You are a helpful assistant for Resh and Thosh. Wait for specific instructions for each query."""
        )
        
        await session.start(agent=agent, room=ctx.room)
        logger.info("🎙️ Agent Session Started")

        # Send data to UI
        async def send_to_ui(text: str, message_type: str):
            """Send message to UI via data channel"""
            try:
                data_packet = json.dumps({
                    "text": text,
                    "type": message_type,
                    "final": True
                })
                await ctx.room.local_participant.publish_data(
                    data_packet.encode('utf-8'),
                    reliable=True
                )
                logger.info(f"📤 Sent to UI ({message_type}): {text[:50]}...")
            except Exception as e:
                logger.error(f"❌ Failed to send to UI: {e}")

        # CRITICAL FIX: Use agent_started_speaking to capture the response
        @session.on("agent_started_speaking")
        def on_agent_started_speaking():
            """Track when agent starts speaking"""
            logger.info("🔊 Agent started speaking")
        
        # CRITICAL FIX: Use agent_stopped_speaking to log interaction
        @session.on("agent_stopped_speaking")
        def on_agent_stopped_speaking():
            """When agent stops speaking, log the interaction"""
            async def handle():
                try:
                    logger.info("🔇 Agent stopped speaking - attempting to log")
                    
                    # Try to get the response from chat context
                    response_text = ""
                    try:
                        if hasattr(session, '_agent') and hasattr(session._agent, '_chat_ctx'):
                            messages = session._agent._chat_ctx.messages
                            if messages and len(messages) > 0:
                                # Get the last assistant message
                                for msg in reversed(messages):
                                    if hasattr(msg, 'role') and msg.role == 'assistant':
                                        if hasattr(msg, 'content'):
                                            response_text = msg.content
                                            break
                                
                                if response_text:
                                    logger.info(f"📝 Captured response: {response_text[:100]}...")
                                    
                                    # Store and send
                                    pending_log["agent_response"] = response_text
                                    await send_to_ui(response_text, "agent_response")
                                    
                                    # Log to Excel
                                    if pending_log["user_request"] and pending_log["agent_response"]:
                                        await log_interaction(
                                            user_request=pending_log["user_request"],
                                            agent_response=pending_log["agent_response"]
                                        )
                                        logger.info("✅ Interaction logged to Excel")
                                        # Clear
                                        pending_log["user_request"] = None
                                        pending_log["agent_response"] = None
                    except Exception as e:
                        logger.error(f"❌ Could not capture from chat context: {e}")
                        
                except Exception as e:
                    logger.error(f"❌ Error in agent_stopped_speaking handler: {e}", exc_info=True)
            
            asyncio.create_task(handle())

        # RAG-enhanced instructions
        async def answer_with_rag(user_question: str):
            """Process user question with RAG context and generate response"""
            # Store the user request
            pending_log["user_request"] = user_question
            pending_log["agent_response"] = None
            
            logger.info(f"🔍 Processing query: '{user_question}'")
            
            query_lower = user_question.lower()
            is_greeting = should_wave(user_question)
            is_founder_query = any(word in query_lower for word in ['founder', 'ceo', 'started', 'owner', 'founders', 'established'])
            is_product_query = any(word in query_lower for word in ['product', 'animate', 'olms', 'ibe', 'offer', 'solution', 'service'])
            
            if is_greeting and not is_founder_query and not is_product_query:
                logger.info("👋 Simple greeting detected - responding with wave")
                context = rag.search("company introduction", top_k=2, is_greeting=True)
                
                enhanced_instruction = f"""Give a brief, friendly response to the greeting.

                Context about Resh & Thosh:
                {context if context else "Resh & Thosh provides innovative travel technology solutions including AI-powered automation and booking systems."}

                INSTRUCTIONS:
                - Say "Hi!" or "Hello!" warmly
                - Briefly mention you can help with questions about Resh & Thosh products or services (1 sentence)
                - Keep total response to 2 sentences maximum
                - Sound natural and enthusiastic
                - Be conversational and welcoming
                """
                
                try:
                    await session.generate_reply(instructions=enhanced_instruction)
                    logger.info("✅ Greeting response requested")
                except Exception as e:
                    logger.error(f"❌ Error generating greeting: {e}")
                return
            
            context = rag.search(user_question, top_k=4, is_greeting=False)
            
            if context:
                logger.info(f"✅ Found RAG context ({len(context)} chars)")
                logger.info(f"📄 Context preview: {context[:200]}...")

                if is_founder_query:
                    enhanced_instruction = f"""The user asked about the founder of Resh and Thosh.

                    Relevant information:
                    {context}

                    INSTRUCTIONS:
                    - State the founder's name clearly in the first sentence: "The founder of Resh and Thosh is [Name]."
                    - Add ONE additional sentence (maximum 25 words) about the company or their mission
                    - Total response: EXACTLY 2 sentences
                    - Do NOT mention any URLs or websites
                    - Be direct and concise
                    - Do NOT add extra details or information

                    Example format:
                    "The founder of Resh and Thosh is [Name]. [One brief sentence about company/vision]."
                    """
                
                elif is_product_query:
                    needs_url_mention = any(meta.get('has_url') for meta in rag.metadata if meta.get('page') == 'products')
                    
                    enhanced_instruction = f"""The user asked: "{user_question}"

                    Relevant information about products:
                    {context}

                    INSTRUCTIONS:
                    - Provide specific details about the product(s) mentioned
                    - Include key features or benefits (2-3 main points)
                    - Keep response to 3-4 sentences total
                    - Be informative but concise
                    - Do NOT provide any URLs directly
                    - {"End with: 'For more details, please visit the Resh and Thosh official website.'" if needs_url_mention else ""}
                    - Sound professional yet conversational
                    - Focus on practical benefits
                    """
                                        
                else:
                    needs_url_mention = any(meta.get('has_url') for meta in rag.metadata)
                    
                    enhanced_instruction = f"""The user asked: "{user_question}"

                    Relevant information:
                    {context}

                    INSTRUCTIONS:
                    - Answer the question directly using ONLY the information provided above
                    - Be specific and mention actual features/details from the content
                    - Keep response to 3-4 sentences
                    - Sound natural and conversational
                    - Do NOT mention any URLs directly
                    - {"Add at the end: 'Visit the Resh and Thosh official website for more information.'" if needs_url_mention else ""}
                    - Answer ONLY their question - do not add greetings
                    - Be helpful and informative
                    """
                                            
            else:
                logger.warning(f"⚠️ No RAG context found")
                enhanced_instruction = f"""The user asked: "{user_question}"

                I don't have specific information about this topic in my knowledge base.

                INSTRUCTIONS:
                - Politely acknowledge you don't have that specific information (1 sentence)
                - Mention you can help with Resh & Thosh products (Animate AI, OLMS, IBE, Manual vs Automation) or company information (1 sentence)
                - Keep response to 2 sentences total
                - Sound friendly, helpful, and apologetic
                - Offer to help with what you do know about
                """
            
            try:
                await session.generate_reply(instructions=enhanced_instruction)
                logger.info("✅ Response requested from LLM")
            except Exception as e:
                logger.error(f"❌ Error generating response: {e}", exc_info=True)
        
        # Capture user speech (AUDIO ONLY - NO TEXT INPUT)
        @session.on("user_speech_committed")
        def on_user_speech_committed(msg):
            async def handle():
                try:
                    if hasattr(msg, 'content'):
                        user_text = msg.content
                        logger.info(f"🎤 User said (VOICE): '{user_text}'")
                        
                        await send_to_ui(user_text, "user_speech")
                        await answer_with_rag(user_text)
                        
                except Exception as e:
                    logger.error(f"❌ Error handling user speech: {e}")
            
            asyncio.create_task(handle())

        # ============================================================
        # Initial greeting with announcement
        # ============================================================
        logger.info("👋 Preparing initial greeting with product announcement...")
        await asyncio.sleep(1.0)
        
        initial_context = rag.search("company introduction", top_k=2, is_greeting=True)
        
        if initial_context and 'Future-ready solutions built to streamline operations' in initial_context:
            initial_context = initial_context.replace(
                'Future-ready solutions built to streamline operations, elevate traveler experiences, and drive growth in the dynamic travel industry.',
                'We offer future-ready solutions to streamline operations and elevate traveler experiences in the travel industry.'
            )
        
        greeting_instruction = f"""Give a warm, professional welcome message introducing Resh and Thosh with a new product announcement.

        Context about the company:
        {initial_context if initial_context else "Resh & Thosh provides innovative travel technology solutions including AI-powered booking systems, automation, and video avatars for the travel industry."}

        INSTRUCTIONS:
        - Start with: "Hello and welcome to Resh & Thosh!"
        - State in ONE clear sentence what Resh and Thosh specializes in (use context - mention travel technology, AI, automation, and video avatars)
        - Add this announcement: "We are excited to announce the launch of our new product designed to clearly highlight the cost difference between manual processes and automated workflows."
        - End with: "If you want to know more about this, just ask for manual versus automation details."
        - Total: EXACTLY 4 sentences
        - Sound warm, welcoming, and professional
        - Be conversational and friendly
        - Do NOT mention any URLs or websites
        - Keep each sentence concise

        Example format:
        "Hello and welcome to Resh & Thosh! [One sentence about what the company does]. We are excited to announce the launch of our new product designed to clearly highlight the cost difference between manual processes and automated workflows. If you want to know more about this, just ask for manual versus automation details."
        """
        
        pending_log["user_request"] = "[Initial Greeting - Auto]"
        
        try:
            await session.generate_reply(instructions=greeting_instruction)
            logger.info("✅ Initial greeting with product announcement requested")
        except Exception as e:
            logger.error(f"❌ Error generating initial greeting: {e}")

        logger.info("✅ AVATAR FULLY LIVE! (Audio Only Mode)")

    except Exception as e:
        logger.error(f"❌ EntryPoint Error: {e}", exc_info=True)
        if excel_workbook:
            async with EXCEL_LOCK:
                try:
                    excel_workbook.save(EXCEL_FILE)
                    logger.info("💾 Saved Excel log upon error.")
                except:
                    pass
        raise

if __name__ == "__main__":
    logger.info("🛠️ Starting Worker - Waiting for Jobs...")
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
