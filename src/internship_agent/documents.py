"""Conservative ATS-readable DOCX generation, using only profile-supported claims."""
from __future__ import annotations

from pathlib import Path
import re
from docx import Document
from docx.shared import Inches, Pt
from .scoring import _contains


def tailoring_report(job: dict, profile: dict) -> dict:
    text = (job.get("title","") + " " + job.get("description","")).lower()
    skills = [s for s in profile.get("skills",[]) if s]
    matching = [s for s in skills if _contains(text, s)]
    remaining = [s for s in skills if s not in matching]
    return {"job_id":job["id"], "title":job["title"],"company":job["company"],
            "matching_verified_skills":matching,"other_verified_skills":remaining,
            "limitations":["No ATS outcome guarantee", "Review all draft content and check eligibility questions",
                           "No skills or accomplishments inferred beyond profile fields"]}


def _add_bullets(doc, bullets):
    for b in bullets:
        if isinstance(b,str) and b.strip():
            doc.add_paragraph(b.strip(), style="List Bullet")


def _ranked_items(items: list[dict], matching_skills: list[str]) -> list[dict]:
    def key(item):
        material = " ".join([item.get("title", ""),item.get("name", "")," ".join(item.get("stack", []))," ".join(item.get("bullets", []))])
        return -sum(_contains(material, s) for s in matching_skills)
    return sorted(items,key=key)


def create_documents(job: dict, profile: dict, output_root: str) -> tuple[str,str]:
    if not profile.get("name") or profile["name"] == "Your Name":
        raise ValueError("Complete and verify config/profile.json before creating documents")
    if not profile.get("experience") and not profile.get("projects"):
        raise ValueError("Provide at least one verified project or role")
    root=Path(output_root).resolve() / re.sub(r"[^A-Za-z0-9_-]","_",job["id"])
    root.mkdir(parents=True,exist_ok=True)
    match=tailoring_report(job,profile)["matching_verified_skills"]
    doc=Document()
    section=doc.sections[0]
    section.top_margin=Inches(.55);section.bottom_margin=Inches(.55)
    section.left_margin=Inches(.7);section.right_margin=Inches(.7)
    normal=doc.styles["Normal"]
    normal.font.name="Aptos";normal.font.size=Pt(9)
    normal.paragraph_format.space_after=Pt(2)
    doc.add_heading(profile["name"],level=0)
    contact=" | ".join(x for x in [profile.get("email"),profile.get("phone"),profile.get("location"),profile.get("linkedin"),profile.get("github")] if x)
    if contact:doc.add_paragraph(contact)
    edu=profile.get("education",{})
    doc.add_heading("EDUCATION",level=2)
    doc.add_paragraph(" | ".join(x for x in [edu.get("school"),edu.get("degree"),edu.get("graduation")] if x))
    certs=profile.get("certifications",[])
    if certs:
        doc.add_heading("CERTIFICATIONS",level=2)
        doc.add_paragraph(" | ".join(certs))
    skills=match+[s for s in profile.get("skills",[]) if s not in match]
    if skills:
        doc.add_heading("TECHNICAL SKILLS",level=2)
        doc.add_paragraph(", ".join(skills))
    for heading, source in [("EXPERIENCE",profile.get("experience",[])),("PROJECTS",profile.get("projects",[]))]:
        if not source:continue
        doc.add_heading(heading,level=2)
        for item in _ranked_items(source,match):
            name=item.get("name") or item.get("title","")
            secondary=item.get("company") or ""
            dates=item.get("dates") or ""
            doc.add_paragraph(" | ".join(x for x in [name,secondary,dates] if x),style="Heading 3")
            _add_bullets(doc,item.get("bullets",[]))
    rp=root/"resume.docx";doc.save(rp)

    letter=Document()
    letter.styles["Normal"].font.size=Pt(10)
    letter.add_paragraph(profile["name"])
    if profile.get("email"):letter.add_paragraph(profile["email"])
    letter.add_paragraph(f"Re: {job['title']} — {job['company']}")
    letter.add_paragraph("Dear Hiring Team,")
    letter.add_paragraph(f"I am applying for the {job['title']} position at {job['company']}. "
                         "My background includes technical coursework and hands-on project experience relevant to this opportunity.")
    detail=", ".join(match[:5])
    if detail:
        letter.add_paragraph(f"My verified experience includes {detail}. I would welcome the opportunity to apply these skills to the responsibilities described in the posting.")
    letter.add_paragraph("Thank you for considering my application. I would appreciate the opportunity to discuss my qualifications further.")
    letter.add_paragraph("Sincerely,\n"+profile["name"])
    lp=root/"cover_letter_DRAFT.docx";letter.save(lp)
    return str(rp),str(lp)
