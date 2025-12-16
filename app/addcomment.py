<%
from momlib import add_comment

if "package" in req.form and "comment" in req.form:
    add_comment(req.form["package"].decode("utf-8"), req.form["comment"].decode("utf-8"))
    if "component" in req.form:
        util.redirect(req, req.form["component"].decode("utf-8") + ".html")
    else:
        req.write("Comment added.")
else:
    req.write(
        "I need at least two parameters: package and comment. "
        "Component is optional."
    )
%>
