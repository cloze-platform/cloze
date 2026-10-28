import argparse
import getpass
import json
import os
import secrets
import sys
import time
from flask import Flask
from sqlalchemy.engine import make_url
from llm_chat import create_app
from llm_chat.extensions import db
from llm_chat.models import (
    User, ProviderPatient, SystemPrompt,
    Model, Conversation, Message, ChatWindow, ChatTemplate, SafetyPlan
)
from llm_chat.services.llm_interface import LLMInterface
from llm_chat.utils.db_roles import ensure_app_user
from llm_chat.utils.passwords import validate_password

app: Flask = create_app()

CREDENTIALS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'instance', 'seed_credentials.txt'
)


def _generate_password():
    """Generate a secure 32-character hex password."""
    return secrets.token_hex(16)


def _save_credentials(credentials):
    """Write seed credentials to instance/seed_credentials.txt."""
    os.makedirs(os.path.dirname(CREDENTIALS_FILE), exist_ok=True)
    with open(CREDENTIALS_FILE, 'w') as f:
        f.write("# Seed account credentials — generated at first run\n")
        f.write(f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n\n")
        for username, password, role in credentials:
            f.write(f"{role:10s}  {username:15s}  {password}\n")
    os.chmod(CREDENTIALS_FILE, 0o600)
    print(f"\nCredentials saved to {CREDENTIALS_FILE}")


def initialize_database(demo=True):
    """Create tables, models and system prompts (idempotent). With demo=True,
    also demo accounts, chats and safety plans for local development."""
    with app.app_context():
        # Create tables if they don't exist
        db.create_all()
        print("Database tables created/verified")

        # Initialize LLM clients
        LLMInterface.initialize_clients(app.config)

        # Default models (only if none exist)
        if not Model.query.first():
            models = [
                Model(name='GPT-3.5 Turbo', provider='openai', model_identifier='gpt-3.5-turbo',
                      config=json.dumps({'temperature': 0.7, 'max_tokens': 1000})),
                Model(name='GPT-4o', provider='openai', model_identifier='gpt-4o',
                      config=json.dumps({'temperature': 0.7, 'max_tokens': 1000})),
                Model(name='GPT-4o Mini', provider='openai', model_identifier='gpt-4o-mini',
                      config=json.dumps({'temperature': 0.7, 'max_tokens': 1000})),
                Model(name='Claude Opus 4.5', provider='anthropic', model_identifier='claude-opus-4-5-20251101',
                      config=json.dumps({'temperature': 0.7, 'max_tokens': 1000})),
                Model(name='Claude Sonnet 4.5', provider='anthropic', model_identifier='claude-sonnet-4-5-20250514',
                      config=json.dumps({'temperature': 0.7, 'max_tokens': 1000})),
                Model(name='Gemini 2.0 Flash', provider='google', model_identifier='gemini-2.0-flash',
                      config=json.dumps({'temperature': 0.7, 'max_tokens': 1000})),
                Model(name='Llama 3.2 1B (Fast)', provider='local',
                      api_endpoint=f"{app.config['OLLAMA_HOST']}/v1/chat/completions",
                      model_identifier='llama3.2:1b',
                      config=json.dumps({'temperature': 0.7, 'max_tokens': 2000})),
                Model(name='Llama 3.2 3B (Balanced)', provider='local',
                      api_endpoint=f"{app.config['OLLAMA_HOST']}/v1/chat/completions",
                      model_identifier='llama3.2:3b',
                      config=json.dumps({'temperature': 0.7, 'max_tokens': 2000})),
                Model(name='Llama 3.1 8B (Quality)', provider='local',
                      api_endpoint=f"{app.config['OLLAMA_HOST']}/v1/chat/completions",
                      model_identifier='llama3.1:8b',
                      config=json.dumps({'temperature': 0.7, 'max_tokens': 2000})),
            ]
            for m in models:
                db.session.add(m)
            print("Created default models")

        # Default system prompts — seed from prompt registry
        from prompts.registry import PromptRegistry
        registry = PromptRegistry.instance()
        if not SystemPrompt.query.first():
            for domain in registry.list_domain_prompts():
                db.session.add(SystemPrompt(
                    name=domain.name,
                    content=domain.description,
                    domain_prompt_id=domain.id,
                ))
            print("Created domain-linked system prompts")
        else:
            # Back-fill domain_prompt_id on existing rows that lack it
            for domain in registry.list_domain_prompts():
                if not SystemPrompt.query.filter_by(domain_prompt_id=domain.id).first():
                    db.session.add(SystemPrompt(
                        name=domain.name,
                        content=domain.description,
                        domain_prompt_id=domain.id,
                    ))
                    print(f"Added domain prompt: {domain.name}")

        if not demo:
            db.session.commit()
            print("Database initialization complete (no demo data).")
            return

        # Track credentials for newly created users
        new_credentials = []

        # Create default admin (only if doesn't exist)
        if not User.query.filter_by(role='admin').first():
            pw = _generate_password()
            admin = User(username='admin', email='admin@example.com', role='admin')
            admin.set_password(pw)
            db.session.add(admin)
            new_credentials.append(('admin', pw, 'admin'))
            print("Created default admin user")

        # Demo provider (only if doesn't exist)
        if not User.query.filter_by(username='provider1').first():
            pw = _generate_password()
            provider = User(username='provider1', email='provider1@example.com', role='provider')
            provider.set_password(pw)
            db.session.add(provider)
            new_credentials.append(('provider1', pw, 'provider'))
            print("Created demo provider")

        # Flush so provider/admin IDs are available for created_by
        db.session.flush()
        provider = User.query.filter_by(username='provider1').first()
        admin = User.query.filter_by(role='admin').first()

        # Demo users (patients) - created by provider1
        demo_users = ['user1', 'user2', 'user3']
        for username in demo_users:
            if not User.query.filter_by(username=username).first():
                pw = _generate_password()
                u = User(
                    username=username, email=f'{username}@example.com', role='user',
                    created_by=provider.id if provider else None,
                )
                u.set_password(pw)
                db.session.add(u)
                new_credentials.append((username, pw, 'patient'))
                print(f"Created demo user: {username}")

        # Save credentials file if any users were created
        if new_credentials:
            _save_credentials(new_credentials)

        # Assign provider to demo users (only if assignments don't exist)
        if provider and admin:
            for username in demo_users:
                patient = User.query.filter_by(username=username).first()
                if patient and not ProviderPatient.query.filter_by(provider_id=provider.id, patient_id=patient.id).first():
                    db.session.add(ProviderPatient(
                        provider_id=provider.id,
                        patient_id=patient.id,
                        assigned_by=admin.id
                    ))
                    print(f"Created provider assignment for {username}")

        # Flush to ensure IDs are assigned for models, prompts, users
        db.session.flush()

        # Demo chat windows with conversations for user1
        provider = User.query.filter_by(username='provider1').first()
        patient1 = User.query.filter_by(username='user1').first()
        model1 = Model.query.first()
        prompt1 = SystemPrompt.query.first()

        if provider and patient1 and model1 and not ChatWindow.query.filter_by(patient_id=patient1.id).first():
            now = time.time()

            # Window 1: completed, 1 conversation (report_ready)
            w1 = ChatWindow(
                patient_id=patient1.id,
                provider_id=provider.id,
                title='Week 1 — Getting Started',
                description='Initial check-in conversation to establish rapport.',
                start_date=now - 14 * 86400,  # 2 weeks ago
                end_date=now - 7 * 86400,      # 1 week ago
                status='report_ready',
            )
            db.session.add(w1)
            db.session.flush()

            t1 = ChatTemplate(
                window_id=w1.id,
                title='Check-In',
                purpose='General check-in to see how things are going',
                model_id=model1.id,
                system_prompt_id=prompt1.id if prompt1 else None,
                order_index=0,
            )
            db.session.add(t1)
            db.session.flush()

            c1 = Conversation(
                user_id=patient1.id,
                title='Check-In',
                model_id=model1.id,
                system_prompt_id=prompt1.id if prompt1 else None,
                window_id=w1.id,
                template_id=t1.id,
                consent_provided=True,
                created_at=now - 13 * 86400,
                updated_at=now - 13 * 86400,
            )
            db.session.add(c1)
            db.session.flush()

            c1_messages = [
                ('user', "Hi, I'm not sure what to talk about. My provider suggested I try this.", now - 13 * 86400),
                ('assistant', "That's completely okay — there's no pressure to have a specific topic. A lot of people start here just to get a feel for what this is like. How has your week been so far?", now - 13 * 86400 + 30),
                ('user', "It's been okay I guess. Work has been stressful and I haven't been sleeping well.", now - 13 * 86400 + 120),
                ('assistant', "I'm sorry to hear that. Stress at work and poor sleep often go hand in hand — when one gets worse, the other tends to follow. What's been going on at work that's been weighing on you?", now - 13 * 86400 + 150),
                ('user', "There's a big deadline coming up and I feel like I can't keep up. I've been staying late but it doesn't seem to help.", now - 13 * 86400 + 300),
                ('assistant', "That sounds really frustrating — putting in the extra effort and still feeling behind. It makes sense that would affect your sleep too, with all that on your mind. Have you been able to do anything to unwind after those long days, even something small?", now - 13 * 86400 + 330),
                ('user', "Not really. I usually just scroll on my phone until I fall asleep. I know that's not great.", now - 13 * 86400 + 500),
                ('assistant', "No judgement at all — that's a really common way people wind down, especially when they're exhausted. It sounds like you're aware it might not be helping with the sleep though. Is sleep something you'd like to work on, or is the work stress feeling more pressing right now?", now - 13 * 86400 + 530),
                ('user', "Probably the work stress. It's the root of everything right now. I used to enjoy my job but lately it just feels like a treadmill.", now - 13 * 86400 + 700),
                ('assistant', "That shift — from enjoying something to it feeling like a treadmill — can be really disheartening. It sounds like something changed beyond just the workload. Do you have a sense of when it started feeling different?", now - 13 * 86400 + 730),
                ('user', "Maybe a few months ago? We got a new manager and everything became about metrics. It doesn't feel like the work matters anymore, just the numbers.", now - 13 * 86400 + 900),
                ('assistant', "That's a meaningful distinction — the work itself hasn't changed but the way it's valued has. When the thing that gave your work meaning gets replaced by metrics, it can drain motivation fast. Is there any part of the job that still feels rewarding?", now - 13 * 86400 + 930),
                ('user', "I still like the problem-solving parts. When I can actually focus on a real problem and work through it. But that's maybe 20% of my day now.", now - 13 * 86400 + 1100),
                ('assistant', "That 20% sounds important — it's the part that still connects you to why you got into this work. I'm curious, when you're in that zone, does the stress feel different? Or does it follow you even into the parts you enjoy?", now - 13 * 86400 + 1130),
                ('user', "When I'm actually focused on a real problem, the stress kind of fades into the background. It's everything around it — the meetings, the status updates, the pressure — that wears me down.", now - 13 * 86400 + 1300),
                ('assistant', "So the work itself can still be a source of flow for you, but the overhead is what's draining your energy. That's actually a useful thing to notice — it means the burnout isn't about the core of what you do, it's about the context around it. That might be worth exploring more — what you can and can't control in that picture.", now - 13 * 86400 + 1330),
            ]
            for role, content, ts in c1_messages:
                db.session.add(Message(conversation_id=c1.id, role=role, content=content, timestamp=ts))
            print("Created demo window 1 (completed, 1 conversation)")

            # Window 2: completed, 2 conversations (report_ready)
            w2 = ChatWindow(
                patient_id=patient1.id,
                provider_id=provider.id,
                title='Week 2 — Coping Strategies',
                description='Exploring coping mechanisms and building a toolkit.',
                start_date=now - 7 * 86400,   # 1 week ago
                end_date=now - 1 * 86400,      # yesterday
                status='report_ready',
            )
            db.session.add(w2)
            db.session.flush()

            t2a = ChatTemplate(
                window_id=w2.id,
                title='Stress Management',
                purpose='Discuss strategies for managing work stress',
                model_id=model1.id,
                system_prompt_id=prompt1.id if prompt1 else None,
                order_index=0,
            )
            t2b = ChatTemplate(
                window_id=w2.id,
                title='Sleep Hygiene',
                purpose='Work on improving sleep habits',
                model_id=model1.id,
                system_prompt_id=prompt1.id if prompt1 else None,
                order_index=1,
            )
            db.session.add(t2a)
            db.session.add(t2b)
            db.session.flush()

            # Conversation 2a: Stress management
            c2a = Conversation(
                user_id=patient1.id,
                title='Stress Management',
                model_id=model1.id,
                system_prompt_id=prompt1.id if prompt1 else None,
                window_id=w2.id,
                template_id=t2a.id,
                consent_provided=True,
                created_at=now - 6 * 86400,
                updated_at=now - 6 * 86400,
            )
            db.session.add(c2a)
            db.session.flush()

            c2a_messages = [
                ('user', "I wanted to talk about what's been going on at work. The deadline passed but now there's another one.", now - 6 * 86400),
                ('assistant', "It sounds like the cycle is continuing. How did you feel after the first deadline passed — was there any relief, or did the next one take over right away?", now - 6 * 86400 + 30),
                ('user', "There was maybe a day where I felt okay, then the next project started and it was right back to feeling overwhelmed.", now - 6 * 86400 + 180),
                ('assistant', "One day of relief before the pressure builds again — that's a tough pattern. It sounds like the stress isn't just about one deadline but more about the pace itself. Have you noticed anything that helps you feel even a little more grounded during these intense stretches?", now - 6 * 86400 + 210),
                ('user', "Honestly, going for walks helps. When I actually do it. But when I'm stressed I just skip it.", now - 6 * 86400 + 400),
                ('assistant', "That's really insightful — you know what works for you, but stress makes it harder to do the very thing that helps. That's such a common pattern. What if the walk didn't have to be a big thing? Even five minutes around the block during a work break?", now - 6 * 86400 + 430),
                ('user', "Yeah, I could probably do that. I think I build it up in my head like it has to be this whole thing.", now - 6 * 86400 + 600),
                ('assistant', "That makes a lot of sense. Sometimes lowering the bar is the most helpful thing — 'getting some air' for five minutes counts just as much as a long walk. Would you want to try that this week and see how it goes?", now - 6 * 86400 + 630),
                ('user', "I'll try. It does help when I actually do it. I actually went for a short walk at lunch today and felt a bit better after.", now - 6 * 86400 + 750),
                ('assistant', "That's great to hear — and the fact that you noticed feeling better is important. Sometimes we don't give ourselves credit for those small moments. What was that like for you?", now - 6 * 86400 + 780),
                ('user', "It was only like ten minutes. I walked to the coffee shop and back. But my head felt clearer when I sat back down. I was less reactive in a meeting after that.", now - 6 * 86400 + 950),
                ('assistant', "Less reactive — that's a really concrete benefit. So the walk didn't just feel nice in the moment, it actually changed how you showed up at work afterward. That's worth noticing.", now - 6 * 86400 + 980),
                ('user', "I hadn't thought about it that way. I guess I always think of self-care as this big separate thing, but that was just part of my day.", now - 6 * 86400 + 1150),
                ('assistant', "Exactly. It doesn't have to be a whole production — it can just be woven into the day. And it sounds like even a short break gave you something that the extra hour at your desk wouldn't have.", now - 6 * 86400 + 1180),
                ('user', "That's true. I think I've been operating on this idea that more hours equals more productivity, but I'm starting to see that's not really how it works.", now - 6 * 86400 + 1350),
                ('assistant', "That's a really important insight. The diminishing returns are real — past a certain point, more time at the desk just produces more stress, not more output. It sounds like you're starting to question that pattern, which is a big first step.", now - 6 * 86400 + 1380),
                ('user', "Yeah. I'm not going to suddenly start leaving on time every day, but maybe I can be more intentional about taking breaks.", now - 6 * 86400 + 1550),
                ('assistant', "That sounds like a really realistic goal — not an overnight change, but a gradual shift toward being more intentional. And you've already seen evidence that it works. Even one walk, one break, one moment of stepping away can change the tone of the rest of your day.", now - 6 * 86400 + 1580),
            ]
            for role, content, ts in c2a_messages:
                db.session.add(Message(conversation_id=c2a.id, role=role, content=content, timestamp=ts))

            # Conversation 2b: Sleep hygiene
            c2b = Conversation(
                user_id=patient1.id,
                title='Sleep Hygiene',
                model_id=model1.id,
                system_prompt_id=prompt1.id if prompt1 else None,
                window_id=w2.id,
                template_id=t2b.id,
                consent_provided=True,
                created_at=now - 4 * 86400,
                updated_at=now - 4 * 86400,
            )
            db.session.add(c2b)
            db.session.flush()

            c2b_messages = [
                ('user', "I've been thinking about the sleep thing. I'm still scrolling on my phone every night and it takes me forever to fall asleep.", now - 4 * 86400),
                ('assistant', "I'm glad you're thinking about it. The phone-before-bed habit is really hard to break because it feels like the easiest way to zone out. What does your evening usually look like after you get home from work?", now - 4 * 86400 + 30),
                ('user', "I eat dinner, watch some TV, then get in bed with my phone. Sometimes I'm on it for an hour or two before I actually sleep.", now - 4 * 86400 + 200),
                ('assistant', "That's a pretty common routine. The tricky part is that the phone light and the endless scrolling keep your brain in 'awake mode' even though your body is tired. Would you be open to experimenting with putting the phone down a bit earlier — even just 20 minutes before you want to sleep?", now - 4 * 86400 + 230),
                ('user', "I could try. What would I do instead though? I feel like I need something to wind down.", now - 4 * 86400 + 400),
                ('assistant', "That's a great question — it's not about just removing the phone, it's about replacing it with something that actually helps you relax. Some people read, some people journal, some people just listen to music. You mentioned journaling helps you sometimes — writing it out, right? That could work well as a wind-down routine.", now - 4 * 86400 + 430),
                ('user', "Yeah, I do like writing things down. It helps get the thoughts out of my head. Maybe I'll try that.", now - 4 * 86400 + 600),
                ('assistant', "That sounds like a solid plan. Even a few minutes of writing before bed could help quiet things down. And if some nights you end up back on the phone, that's okay — it's about building the habit gradually, not flipping a switch overnight.", now - 4 * 86400 + 630),
                ('user', "I actually tried it last night. I put my phone on the dresser across the room and wrote in a notebook for about ten minutes.", now - 4 * 86400 + 800),
                ('assistant', "That's a great step — putting the phone physically out of reach is a smart move. How did it go? Did you notice anything different about falling asleep?", now - 4 * 86400 + 830),
                ('user', "I think I fell asleep faster than usual. But it was hard at first. I kept wanting to check my phone. My brain just felt restless.", now - 4 * 86400 + 1000),
                ('assistant', "That restlessness is completely normal — your brain is used to the constant stimulation of scrolling, so when you take it away, there's a gap. The journaling is a good way to redirect that energy. What did you end up writing about?", now - 4 * 86400 + 1030),
                ('user', "Mostly just stuff from the day. Things that annoyed me, a few things I need to do tomorrow. Nothing deep, just kind of a brain dump.", now - 4 * 86400 + 1200),
                ('assistant', "A brain dump is exactly right — you're essentially offloading all those thoughts onto paper so they don't keep circling in your head while you try to sleep. Some people find that writing a short to-do list for tomorrow is especially helpful because it signals to your brain that you don't need to hold onto those tasks anymore.", now - 4 * 86400 + 1230),
                ('user', "That makes sense. I did write down some things for tomorrow and I remember feeling a little lighter after that. Like I'd given myself permission to stop thinking about it.", now - 4 * 86400 + 1400),
                ('assistant', "That's exactly it — giving yourself permission to set it down for the night. That's a skill, and it sounds like the writing is helping you practice it. How are you feeling about trying it again tonight?", now - 4 * 86400 + 1430),
                ('user', "I'm going to keep doing it. It's only been one night but it already felt better than my usual routine. And I think the sleep was actually better quality — I didn't wake up as much.", now - 4 * 86400 + 1600),
                ('assistant', "That's really encouraging. Better quality sleep even after one night is a good sign. And the fact that you're willing to keep going with it — that matters. Remember, some nights will be harder than others and that's okay. The pattern over time is what counts, not any single night.", now - 4 * 86400 + 1630),
            ]
            for role, content, ts in c2b_messages:
                db.session.add(Message(conversation_id=c2b.id, role=role, content=content, timestamp=ts))
            print("Created demo window 2 (completed, 2 conversations)")

        # Demo safety plans for test users
        provider = User.query.filter_by(username='provider1').first()
        if provider:
            for username in ['user1']:
                patient = User.query.filter_by(username=username).first()
                if patient and not SafetyPlan.query.filter_by(patient_id=patient.id).first():
                    plan = SafetyPlan(
                        patient_id=patient.id,
                        status='active',
                        version=1,
                        approved_at=time.time(),
                        approved_by=provider.id,
                    )
                    plan.set_warning_signs([
                        {'sign': 'Withdrawing from friends', 'severity': 4, 'context': 'Usually happens after stressful work weeks'},
                        {'sign': 'Difficulty sleeping', 'severity': 3, 'context': 'Precedes low mood episodes'},
                        {'sign': 'Losing interest in hobbies', 'severity': 3, 'context': 'Sign of deepening withdrawal'},
                    ])
                    plan.set_coping_strategies([
                        {'strategy': 'Going for a walk outside', 'effectiveness': 4, 'context': 'Works best in daylight', 'patient_language': 'getting some air'},
                        {'strategy': 'Calling a friend', 'effectiveness': 3, 'context': 'Harder when feeling very low', 'patient_language': 'checking in with someone'},
                        {'strategy': 'Journaling', 'effectiveness': 4, 'context': 'Helps process difficult thoughts', 'patient_language': 'writing it out'},
                    ])
                    plan.set_support_network([
                        {'person': 'Sarah', 'relationship': 'Sister', 'contact_preference': 'Text first, then call', 'comfort_level': 5},
                        {'person': 'James', 'relationship': 'Close friend', 'contact_preference': 'Call anytime', 'comfort_level': 4},
                    ])
                    plan.set_reasons_for_living([
                        {'reason': 'My sister and her kids', 'context': 'Family is very important'},
                        {'reason': 'I want to finish my degree', 'context': 'Long-term goal'},
                        {'reason': 'My dog, Charlie', 'context': 'Daily companionship'},
                    ])
                    plan.set_anti_patterns([
                        {'pattern': 'ask directly about a suicidal plan', 'reason': 'feels interrogative and triggering', 'severity': 3, 'source': 'provider', 'visible_to_patient': True},
                        {'pattern': 'suggest calling crisis hotlines without context', 'reason': 'negative past experiences with crisis lines', 'severity': 2, 'source': 'provider', 'visible_to_patient': True},
                        {'pattern': 'use the phrase "just think positive"', 'reason': 'dismissive of their experience', 'severity': 2, 'source': 'patient', 'visible_to_patient': True},
                        {'pattern': 'bring up family conflicts unprompted', 'reason': 'complex family dynamics — let patient lead', 'severity': 2, 'source': 'provider', 'visible_to_patient': False},
                    ])
                    plan.set_care_team([
                        {'name': provider.username, 'role': 'provider', 'contact_protocol': 'Contact through Cloze platform', 'after_hours': 'Call clinic emergency line'},
                    ])
                    plan.set_emergency_plan({
                        'activation_conditions': 'Expression of active suicidal ideation with means or plan',
                        'preferred_facility': 'City General Hospital — Psychiatric Emergency',
                        'contraindications': 'Avoid restraint if possible — history of trauma response',
                    })
                    plan.provider_notes = 'Patient has history of major depressive episodes. Currently stable on medication. Family dynamics are complex — father is estranged. Sister is primary support.'
                    db.session.add(plan)
                    print(f"Created demo safety plan for {username}")

            # user2 gets a draft plan (provider created, patient not yet filled in)
            patient2 = User.query.filter_by(username='user2').first()
            if patient2 and not SafetyPlan.query.filter_by(patient_id=patient2.id).first():
                plan2 = SafetyPlan(
                    patient_id=patient2.id,
                    status='draft',
                    version=1,
                )
                plan2.set_anti_patterns([
                    {'pattern': 'use CBT reframing techniques', 'reason': 'patient is resistant to CBT framing', 'severity': 2, 'source': 'provider', 'visible_to_patient': True},
                ])
                plan2.set_care_team([
                    {'name': provider.username, 'role': 'provider', 'contact_protocol': 'Contact through Cloze platform', 'after_hours': ''},
                ])
                plan2.set_emergency_plan({
                    'activation_conditions': 'Active suicidal ideation',
                    'preferred_facility': '',
                    'contraindications': '',
                })
                plan2.provider_notes = 'New patient. Intake completed. Awaiting patient safety plan input.'
                db.session.add(plan2)
                print("Created draft safety plan for user2")

        # Commit all changes at once
        try:
            db.session.commit()
            print("Database initialization complete.")
        except Exception as e:
            db.session.rollback()
            print(f"Database initialization completed with some existing data: {e}")

def init_production():
    """Tables and reference data, then the app's restricted database user if
    CLOZE_APP_DATABASE_URL is set. Run as the database owner."""
    initialize_database(demo=False)
    app_url = app.config["CLOZE_APP_DATABASE_URL"]
    if app_url:
        with app.app_context():
            ensure_app_user(db.engine, app_url)
        print(f"Database user {make_url(app_url).username!r} is up to date.")


def create_admin(username, email):
    """Create an admin account, prompting for the password so it stays out of
    shell history and logs."""
    with app.app_context():
        if User.query.filter((User.username == username) | (User.email == email)).first():
            sys.exit(f"A user with username {username!r} or email {email!r} already exists.")
        password = getpass.getpass("Password: ")
        error = validate_password(password)
        if error:
            sys.exit(error)
        if getpass.getpass("Repeat password: ") != password:
            sys.exit("Passwords don't match.")
        admin = User(username=username, email=email, role='admin')
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        print(f"Created admin {username!r}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Cloze setup. With no command: seed demo data and run the dev server.")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "init-production",
        help="Create tables, models and system prompts (no demo data), and the app's database user.")
    create_admin_cmd = commands.add_parser(
        "create-admin", help="Create an admin account (prompts for the password).")
    create_admin_cmd.add_argument("username")
    create_admin_cmd.add_argument("email")
    args = parser.parse_args()

    if args.command == "init-production":
        init_production()
    elif args.command == "create-admin":
        create_admin(args.username, args.email)
    else:
        initialize_database()
        app.run(debug=True, host="0.0.0.0", port=5051)
