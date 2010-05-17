<%
from momlib import *
from cgi import escape

if req.form.has_key("package") and req.form.has_key("comment"):
    add_comment(req.form["package"], req.form["comment"])
    if req.form.has_key("component"):
        util.redirect(req, req.form["component"]+".html")
    else:
        req.write("Comment added.")
else:
    req.write("I need at least two parameters: package and comment. Component is optional.")
%>
