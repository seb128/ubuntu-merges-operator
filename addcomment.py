<%
from momlib import add_comment

if "package" in req.form and "comment" in req.form:
    add_comment(req.form["package"], req.form["comment"])
    if "component" in req.form:
        util.redirect(req, req.form["component"] + ".html")
    else:
        req.write("Comment added.")
else:
    req.write(
        "I need at least two parameters: package and comment. "
        "Component is optional."
    )
%>
