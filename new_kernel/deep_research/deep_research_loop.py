# DeepResearchLoop：mode=deep 时替代 TeachingLoop，复用同一套 read-only 工具但放开 max_steps / max_react_iterations，按 phase emit DeepResearchProgressEvent，最终也只通过 TeacherAgent 出可见正文。
