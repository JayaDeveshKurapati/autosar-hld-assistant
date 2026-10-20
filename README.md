# AUTOSAR HLD Document Analysis Assistant - Capstone Submission

| Folder | Contents |
|---|---|
| Synopsis/ | Project synopsis (Word) |
| Input_Data/ | Sample HLD v1, v2 and ARXML (knowledge base) |
| Code/ | Full source code, tests, requirements (self-contained; `streamlit run app.py`) |
| Model_Prompts_Config/ | LLM prompt, retrieval and runtime configuration |
| Evaluation_Results/ | Test output, findings, Q&A probe, revision comparison, metrics |
| Documentation/ | Technical report (Word; export PDF before submission) and diagrams |
| Video/ | Demo video or link |
| Declarations/ | Signed academic integrity and AI-tool usage declarations |

## Run
```
cd Code
pip install -r requirements.txt
streamlit run app.py          # sidebar > Load sample documents
python -m hld_assistant analyze sample_data/brake_system_hld_v1.txt
pytest
```
Repository link: [paste]
