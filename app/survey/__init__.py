"""The survey: everything between a pin on the map and a designed business.

models       the site, the owner's brief and a run's state
pipeline     a survey run, streamed as events
evidence     what the agent sees, and what each gap says in words
concepts     business concepts: the Qloo-tool agent and its checks, the evidence rules and grounding
constraints  the owner's notes, read into rules both the agent and the evidence rules respect
intents      what the owner asked for: a verdict on a business (with the chain check), or how to improve a place
design       the design sheet, built with audience, experience and launch
audience     who the places people here love draw, from Qloo's audience data, read as leans
experience   what local fans of a category also love, across domains: what to play, screen and host
launch       the launch plan: who to reach, where, when, and what can truthfully be said
kit          the launch kit: checked ad copy, a poster, tracked links and the report (app/kits.py builds it)
dossier      the kit's report: the case for one storefront business, for a landlord, a lender or a partner
snapshot     a finished run as compressed JSON and back, so it outlives the process that ran it
"""
