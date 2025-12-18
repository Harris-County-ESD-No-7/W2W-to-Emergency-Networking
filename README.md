# W2W-to-Emergency-Networking
This converts a When To Work schedule into Emergency Reporting. 

We were told that Emergency Networking was still working on an integration with WhenToWork (W2W). W2W has worked very well for us in the past. We would like to keep using the product but need a single place to manage the schedule. Both products provide an API interface that allows for the agency to interact with it's data programatically. 

I am using chron to run the script at regular intervals. At this point the script has no idea when it ran last. 

## 12/17/2025
The script now uses the category to determine which apparatus the employee is riding

