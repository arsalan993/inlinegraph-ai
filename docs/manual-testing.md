# Manual testing conversations

These examples check selection, branch continuity, acceptance, and context carry-forward in the current application. Use a real Groq model and start a new conversation for each example. Mock mode uses fixed responses and is suitable for interface inspection, not for checking whether the model follows these constraints.

Open **See logs** before sending each final main-chat question. The debugger records new requests while it is open. Model wording may differ; check the conditions below rather than an exact response. These are suggested manual checks, not published quality scores or guarantees.

## Example one: correct a dinner plan

This checks whether a correction made in a selected-text branch is retained by the next main-chat answer.

1. Ask in the main chat:

   > Plan a simple dinner for four people: creamy mushroom pasta with Parmesan, garlic bread, and a yogurt dessert. Briefly explain each dish.

2. Select the phrase about **creamy mushroom pasta with Parmesan** in the answer. Click **Ask** and send:

   > Correction: one guest has a dairy allergy. Make the entire dinner dairy-free. Use oat cream for the pasta, nutritional yeast instead of Parmesan, olive oil for the garlic bread, and fruit sorbet for dessert.

3. Read the branch response and click **Accept**. Check that the interface confirms acceptance for the next main-chat question.

4. Return to the main chat and ask:

   > Now give me the shopping list with quantities for four people, followed by the cooking steps.

**Expected result:** The shopping list and cooking steps use oat cream, nutritional yeast, olive oil, and fruit sorbet. They exclude Parmesan, butter, dairy cream, and yogurt. The final question does not repeat the correction, so the substitutions check whether branch context carried forward.

**Inspect the trace:** The final model input should include the dietary correction and accepted branch reply. The graph should connect the branch answer to the final main question with **included as context**. The original dinner answer remains visible.

## Example two: clarify and adapt a study plan

This checks multiple selection, conversational follow-ups within a branch, and retention of the latest branch constraints in a subsequent main-chat schedule.

1. Ask in the main chat:

   > Create a seven-day study plan for a Python beginner, assuming one hour per day. Include lessons and short exercises about lists and dictionaries.

2. Select a phrase about **lists**, choose **Add another**, and select a phrase about **dictionaries** from the same answer. Click **Ask** and send:

   > Explain the difference between lists and dictionaries with a tiny example of each. Also adapt my study plan: I can study only 25 minutes each weekday evening and cannot study on weekends.

3. Continue within the branch:

   > Split each session into a five-minute recap, a fifteen-minute exercise, and a five-minute review. Keep the code examples simple.

   Read the response and click **Accept** after this follow-up.

4. Return to the main chat and ask:

   > Give me the final weekly schedule with exact activities and timing, including the small code exercises.

**Expected result:** Five weekday sessions, each lasting 25 minutes with the 5/15/5 split. The schedule includes simple list and dictionary exercises, with no weekend sessions or one-hour sessions. The final question does not repeat the timing constraints.

**Inspect the trace:** The final model input should include both selected ranges and their source paragraphs, the first branch question, the follow-up, and the branch replies. The graph should show the selections and branch conversation, with a context link to the final question.

## If the answer does not match

Inspect the final request in **See logs**. If a branch turn is missing, record the steps and the missing context. If all turns are present but the answer ignores a constraint, the model did not apply the supplied context correctly. Graph edges document inclusion; they do not guarantee correct reasoning. The advisory runtime reviewer does not verify factual accuracy.
