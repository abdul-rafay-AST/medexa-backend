# Medexa Clinical Pipeline Test Script
**Scenario:** Right Shoulder Adhesive Capsulitis (Frozen Shoulder) / Rotator Cuff
**Purpose:** Stress-test Path A (Billing & NCCI), Path B (Live Assistant), and Path C (SOAP & Patient Summary).

---

## The Transcript (Paste in chunks into the Simulator)

### Chunk 1 (Subjective & Intake)
**Doctor:** Good morning, Sarah. How is the right shoulder feeling today?
**Patient:** Good morning. It's been pretty stiff, especially in the mornings. I tried to reach for a cup in the upper cabinet yesterday and got a really sharp catch. 
**Doctor:** I see. On a scale of 0 to 10, how bad was that sharp catch of pain?
**Patient:** It shot up to about a 7 out of 10, but right now resting, it's just a dull ache, maybe a 3.
**Doctor:** Okay. Have you noticed any numbness or tingling down your arm into your fingers?
**Patient:** No, no tingling, just the stiffness and the pain right around the front of the shoulder.

### Chunk 2 (Objective & Manual Therapy)
**Doctor:** Let's take a look. I want to check your active range of motion first. Try to raise your right arm straight up in front of you. 
**Patient:** Ah, that's about as far as I can go.
**Doctor:** Looks like shoulder flexion is limited to about 90 degrees today. External rotation is also restricted to around 15 degrees. Go ahead and lie down on your back. I'm going to perform some grade three inferior and anterior joint mobilizations on the glenohumeral joint to help stretch out that capsule. 
**Patient:** Okay. Oh, that feels a bit tight.
**Doctor:** Just breathe through it. I'll also do some soft tissue mobilization on the pectoralis minor and upper trapezius, as they feel very guarded. We'll spend about 15 minutes doing this manual therapy.

### Chunk 3 (Therapeutic Exercise & NCCI Trigger)
**Doctor:** Alright, let's move on to some movement. I want you to grab that yellow resistance band. We are going to do some isometric external rotations to help stabilize the cuff. 
**Patient:** Like this?
**Doctor:** Exactly. Keep your elbow tucked into your side. Let's do 2 sets of 10. This therapeutic exercise is going to rebuild your strength without aggravating the joint.
**Patient:** It's burning a little bit, but not painful.
**Doctor:** That's the muscle fatigue we want. We'll follow this up with some wall walk exercises for active-assisted range of motion. We've spent about 15 minutes on these exercises today.

### Chunk 4 (Assessment & Plan)
**Doctor:** You did great today. The joint mobilization definitely helped free up a few degrees of motion, but we still have a ways to go with the adhesive capsulitis. 
**Patient:** What should I be doing at home?
**Doctor:** Keep doing the pendulum exercises we talked about last time. I want you to come back in on Thursday so we can continue with the manual therapy and start introducing some neuromuscular re-education for your scapular control.
**Patient:** Sounds like a plan. Thank you, doctor.

---

## 🎯 Expected Pipeline Outputs

### Path A (Clinical Entities & Billing Rules)
- **Entities Extracted Natively (Sidebar):** 
  - *Body Regions:* Right shoulder, glenohumeral joint, pectoralis minor, upper trapezius.
  - *Symptoms:* Sharp catch, dull ache, stiffness.
  - *Measurements:* Flexion 90 degrees, External rotation 15 degrees, Pain scale 7/10.
- **Billing CPT Detection:**
  - **97140 (Manual Therapy):** Triggered by "joint mobilizations" and "soft tissue mobilization".
  - **97110 (Therapeutic Exercise):** Triggered by "isometric external rotations" and "wall walk exercises".
- **Alerts / NCCI Conflicts:**
  - *NCCI Bundling Alert:* Because `97140` and `97110` are often bundled when performed on the same body region, Path A should throw a warning. The `DocumentationReviewBuilder` should explicitly advise you: *"BEST BILLING PATH: Append Modifier 59 to override the bundling edit if the service was distinct and separate."*

### Path B (Live Assistant Hints)
While running the chunks, Path B should trigger in your "Assistant Suggestions" tab. 
- *Expected Hint:* Notice that the doctor asked about the pain scale, but **failed to ask about the patient's compliance with their previous Home Exercise Program (HEP)** until the very end when the patient had to ask about it. 
- *Expected Hint:* The doctor did not take an objective strength measurement (MMT) before starting the exercises. Path B might prompt: *"Consider documenting manual muscle testing (MMT) grades for the rotator cuff prior to strengthening."*

### Path C (SOAP Note & Patient Summary)
When you click **Finalize Session**, the enhanced Path C prompt will generate:

**1. Industry-Standard SOAP Note:**
- **Subjective:** "Patient reports right shoulder stiffness, worse in mornings. Experienced a sharp catch of pain (7/10) reaching for upper cabinet. Resting pain is 3/10. Denies radicular symptoms/tingling."
- **Objective:** "Active ROM limited: Shoulder flexion 90 degrees, external rotation 15 degrees. Interventions: 15 mins Manual Therapy (Grade III inferior/anterior GH mobilizations, STM to pec minor/upper trap). 15 mins Therapeutic Exercise (isometric ER with yellow band 2x10, wall walks)."
- **Assessment:** "Patient presents with right shoulder adhesive capsulitis with significant ROM deficits and guarding. Demonstrated good tolerance to manual therapy and therapeutic exercise today without adverse pain response. Continued skilled PT is medically necessary to restore functional reach."
- **Plan:** "Continue skilled PT 2x/week. Next session to include manual therapy and introduce neuromuscular re-education for scapular control. Patient instructed to continue pendulum HEP."

**2. Dynamic Patient Summary:**
> *"Great job today, Sarah! We focused on loosening up your right shoulder using hands-on mobilization and some targeted resistance band exercises. You did an excellent job pushing through the stiffness, and we are already seeing small improvements in how far you can move your arm. Remember to keep up with your pendulum exercises at home, and I will see you on Thursday to keep building your strength!"*
